"""Cross-event permissions, revision safety and durable lifecycle behavior."""
import copy
import json
import os
import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

if __package__:
    from .test_mvp_handlers import FakeTable, load_app, event, body
else:
    from test_mvp_handlers import FakeTable, load_app, event, body


class Phase2Tests(unittest.TestCase):
    def setUp(self):
        os.environ['APP_TABLE_NAME'] = 'test-table'
        self.table = FakeTable()
        for club in ('one', 'two'):
            self.table.put_item(Item={'PK': f'CLUB#{club}', 'SK': 'META', 'name': club})
            for user, role in [('admin', 'admin'), ('friend', 'friend'), ('guest', 'guest')]:
                self.table.put_item(Item={'PK': f'CLUB#{club}', 'SK': f'MEMBER#{user}', 'clubId': club, 'userId': user,
                                         'role': role, 'status': 'active', 'GSI1PK': f'USER#{user}', 'GSI1SK': f'CLUB#{club}'})
        self.night('a')
        self.showtime('a', 's1', '2099-01-01T18:00:00Z')
        self.showtime('a', 's2', '2099-01-01T19:00:00Z')

    def night(self, identifier, club='one', status='voting', date='2099-01-01'):
        item = {'PK': f'CLUB#{club}', 'SK': f'MOVIE_NIGHT#{identifier}', 'clubId': club, 'movieNightId': identifier,
                'GSI2PK': f'MOVIE_NIGHT#{identifier}', 'GSI2SK': 'META', 'status': status, 'targetDate': date,
                'movie': {'provider': 'tmdb', 'externalId': identifier, 'title': identifier, 'runtime': 120},
                'votingClosedAt': '2020-01-01T00:00:00Z', 'version': 1}
        self.table.put_item(Item=item)
        return self.table.items[(item['PK'], item['SK'])]

    def showtime(self, night, identifier, start):
        self.table.put_item(Item={'PK': f'MOVIE_NIGHT#{night}', 'SK': f'SHOWTIME#{identifier}', 'movieNightId': night,
                                 'showtimeId': identifier, 'startsAtUtc': start, 'theaterName': 'Cinema', 'screenFormat': 'Standard', 'status': 'approved'})

    def call(self, handler, identifier='a', payload=None, user='admin', path=None, method='POST', query=None, club=None):
        app = load_app(handler, self.table)
        return app.handler(event(method, path=path, movie_night_id=identifier, club_id=club, user_id=user, body=payload, query=query), None)

    def confirm(self, showtime='s1', version=1, key='confirm', **kwargs):
        return self.call('confirm-showtime-lambda', payload={'showtimeId': showtime, 'expectedVersion': version, 'idempotencyKey': key}, **kwargs)

    def records(self, pk):
        return [v for (p, _), v in self.table.items.items() if p == pk]

    def test_confirmation_retry_is_atomic_and_does_not_resend(self):
        first = self.confirm()
        self.assertEqual(200, first['statusCode'], first)
        night = body(first)['movieNight']
        self.assertEqual(1, night['planRevision'])
        self.assertEqual(2, night['version'])
        self.assertEqual(night, body(self.confirm())['movieNight'])
        self.assertEqual(1, len(self.records('NOTIFICATION_OUTBOX')))
        self.assertEqual(1, len(self.records('NOTIFICATION_DUE')))
        self.assertEqual(409, self.confirm(showtime='s2')['statusCode'])
        self.assertEqual(409, self.confirm(showtime='s2', key='another')['statusCode'])

    def test_changed_plan_preserves_old_participation_and_requires_revision(self):
        self.confirm()
        rsvp = self.call('update-rsvp-lambda', payload={'status': 'going', 'ticketStatus': 'purchased'}, user='friend', method='PUT')
        self.assertEqual(200, rsvp['statusCode'])
        changed = self.confirm('s2', 2, 'change')
        self.assertEqual(200, changed['statusCode'], changed)
        night = body(changed)['movieNight']
        self.assertEqual((2, 1), (night['planRevision'], night['calendarSequence']))
        self.assertEqual('s1', night['previousPlan']['showtimeId'])
        prior = self.table.items[('MOVIE_NIGHT#a', 'RSVP#friend')]
        self.assertEqual(('going', 'purchased', 1), (prior['status'], prior['ticketStatus'], prior['rsvpPlanRevision']))
        for revision in (None, 1, True):
            payload = {'status': 'going', 'ticketStatus': 'purchased'}
            if revision is not None:
                payload['planRevision'] = revision
            self.assertEqual(409, self.call('update-rsvp-lambda', payload=payload, user='friend', method='PUT')['statusCode'])
        self.assertEqual(200, self.call('update-rsvp-lambda', payload={'status': 'maybe', 'ticketStatus': 'not_purchased', 'planRevision': 2}, user='friend', method='PUT')['statusCode'])
        attendance = body(self.call('get-attendance-lambda', method='GET'))
        self.assertEqual(1, attendance['summary']['maybe'])

    def test_acknowledgement_does_not_change_tickets_or_rsvp(self):
        self.confirm()
        self.call('update-rsvp-lambda', payload={'status': 'going', 'ticketStatus': 'purchased'}, user='friend', method='PUT')
        self.confirm('s2', 2, 'change')
        saved = copy.deepcopy(self.table.items[('MOVIE_NIGHT#a', 'RSVP#friend')])
        url = '/movie-nights/a/plan-acknowledgement/me'
        self.assertEqual(409, self.call('list-movie-nights-lambda', payload={'planRevision': 1}, path=url, method='PUT', user='friend')['statusCode'])
        self.assertEqual(200, self.call('list-movie-nights-lambda', payload={'planRevision': 2}, path=url, method='PUT', user='friend')['statusCode'])
        self.assertEqual(saved, self.table.items[('MOVIE_NIGHT#a', 'RSVP#friend')])
        detail = body(self.call('list-movie-nights-lambda', method='GET', user='friend'))
        self.assertEqual(2, detail['currentUserAcknowledgement']['acknowledgedPlanRevision'])
        attendance = body(self.call('get-attendance-lambda', method='GET'))
        self.assertEqual(0, attendance['summary']['going'])
        self.assertEqual(1, attendance['summary']['needsReconfirmation'])
        self.assertEqual(1, attendance['summary']['ticketsNeedReview'])

    def test_noop_key_is_persisted_without_revision_or_notice(self):
        self.confirm()
        before = copy.deepcopy(self.table.items[('CLUB#one', 'MOVIE_NIGHT#a')])
        result = self.confirm('s1', 2, 'noop')
        self.assertEqual(200, result['statusCode'])
        self.assertEqual(before, self.table.items[('CLUB#one', 'MOVIE_NIGHT#a')])
        self.assertEqual(1, len(self.records('NOTIFICATION_OUTBOX')))
        self.assertEqual(409, self.confirm('s2', 2, 'noop')['statusCode'])

    def test_same_showtime_with_material_snapshot_change_is_revisioned(self):
        self.confirm()
        self.table.items[('MOVIE_NIGHT#a', 'SHOWTIME#s1')]['screenFormat'] = 'IMAX'
        changed = body(self.confirm('s1', 2, 'format'))['movieNight']
        self.assertEqual(2, changed['planRevision'])
        self.assertEqual('Standard', changed['previousPlan']['screenFormat'])

    def test_failed_transaction_leaves_no_plan_audit_retry_or_notification(self):
        before = copy.deepcopy(self.table.items)
        self.table.fail_transact = True
        with self.assertLogs('cmc_shared', level='ERROR'):
            result = self.confirm()
        self.assertEqual(500, result['statusCode'])
        self.assertEqual(before, self.table.items)
        self.table.fail_transact = False
        self.assertEqual(200, self.confirm()['statusCode'])

    def test_membership_removed_between_read_and_transaction_blocks_confirmation(self):
        app = load_app('confirm-showtime-lambda', self.table)
        real = app.get_showtime
        def revoke(*args):
            self.table.items[('CLUB#one', 'MEMBER#admin')]['status'] = 'removed'
            return real(*args)
        with patch.object(app, 'get_showtime', side_effect=revoke):
            result = app.handler(event('POST', movie_night_id='a', user_id='admin', body={'showtimeId': 's1'}), None)
        self.assertEqual(409, result['statusCode'])
        self.assertEqual([], self.records('NOTIFICATION_OUTBOX'))

    def test_stale_completion_cancellation_and_independent_nights(self):
        self.confirm()
        self.night('b', status='planning', date='2098-01-01')
        self.night('c', status='voting')
        original = copy.deepcopy(self.table.items[('CLUB#one', 'MOVIE_NIGHT#b')])
        self.assertEqual(409, self.call('cancel-movie-night-lambda', payload={'expectedVersion': 1})['statusCode'])
        cancelled = self.call('cancel-movie-night-lambda', payload={'expectedVersion': 2, 'idempotencyKey': 'cancel'})
        night = body(cancelled)['movieNight']
        self.assertEqual(('cancelled', 2, 1), (night['status'], night['planRevision'], night['calendarSequence']))
        self.assertEqual(night, body(self.call('cancel-movie-night-lambda', payload={'expectedVersion': 2, 'idempotencyKey': 'cancel'}))['movieNight'])
        self.assertEqual(409, self.call('complete-movie-night-lambda', payload={'expectedVersion': 2})['statusCode'])
        self.assertEqual(original, self.table.items[('CLUB#one', 'MOVIE_NIGHT#b')])
        self.assertEqual(409, self.call('update-rsvp-lambda', method='PUT', payload={'status': 'going', 'planRevision': 2})['statusCode'])
        calendar = self.call('get-calendar-lambda', method='GET')
        self.assertEqual(200, calendar['statusCode'])
        self.assertEqual('cancelled', body(calendar)['movieNight']['status'])

    def test_schedule_order_is_chronological_while_active_remains_confirmed_first(self):
        self.confirm()
        self.night('b', status='planning', date='2098-01-01')
        page = body(self.call('list-movie-nights-lambda', identifier=None, club='one', method='GET'))
        self.assertEqual(['b', 'a'], [n['movieNightId'] for n in page['movieNights']])
        active = body(self.call('get-active-movie-night-lambda', identifier=None, club='one', method='GET'))
        self.assertEqual('a', active['movieNight']['movieNightId'])

    def test_agenda_pagination_current_membership_scope_and_guest_restrictions(self):
        self.night('b', club='two', status='planning')
        def agenda(user='friend', query=None):
            return self.call('list-movie-nights-lambda', identifier=None, path='/me/movie-nights', method='GET', user=user, query=query)
        first = body(agenda(query={'limit': '1'}))
        second = body(agenda(query={'limit': '1', 'cursor': first['nextCursor']}))
        self.assertEqual(['a', 'b'], [first['movieNights'][0]['movieNightId'], second['movieNights'][0]['movieNightId']])
        self.assertEqual('two', second['movieNights'][0]['clubName'])
        self.assertEqual(400, agenda(user='admin', query={'cursor': first['nextCursor']})['statusCode'])
        self.table.items[('CLUB#two', 'MEMBER#friend')]['status'] = 'removed'
        self.assertEqual(['a'], [n['movieNightId'] for n in body(agenda())['movieNights']])
        self.assertEqual([], body(agenda(user='guest'))['movieNights'])
        self.assertEqual(400, agenda(query={'scope': 'all'})['statusCode'])
        self.assertEqual(403, self.call('list-movie-nights-lambda', identifier='b', user='friend', method='GET')['statusCode'])

    def test_recent_agenda_uses_thirty_day_lookback(self):
        for identifier, days in [('recent', 2), ('old', 31)]:
            night = self.night(identifier, status='completed')
            night['completedAt'] = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat().replace('+00:00', 'Z')
        result = body(self.call('list-movie-nights-lambda', identifier=None, path='/me/movie-nights', method='GET', query={'scope': 'recent'}))
        self.assertEqual(['recent'], [n['movieNightId'] for n in result['movieNights']])

    def test_planning_patch_is_versioned_and_cannot_move_confirmed_plan(self):
        self.night('plan', status='planning')
        result = self.call('list-movie-nights-lambda', 'plan', {'version': 1, 'targetDate': '2099-02-01'}, method='PATCH')
        self.assertEqual(2, body(result)['movieNight']['version'])
        self.assertEqual(409, self.call('list-movie-nights-lambda', 'plan', {'version': 1}, method='PATCH')['statusCode'])
        self.assertEqual(403, self.call('list-movie-nights-lambda', 'plan', {'version': 2}, method='PATCH', user='friend')['statusCode'])
        self.confirm()
        self.assertEqual(409, self.call('list-movie-nights-lambda', payload={'version': 2, 'targetDate': '2099-02-01'}, method='PATCH')['statusCode'])

    def test_legacy_record_defaults_accept_first_plan_rsvp(self):
        night = self.table.items[('CLUB#one', 'MOVIE_NIGHT#a')]
        night.pop('version')
        night.update(status='confirmed', confirmedShowtimeId='s1')
        result = self.call('update-rsvp-lambda', payload={'status': 'going'}, method='PUT')
        self.assertEqual(200, result['statusCode'])
        self.assertEqual(1, body(result)['rsvp']['rsvpPlanRevision'])
        detail = body(self.call('list-movie-nights-lambda', method='GET'))
        self.assertEqual((0, 1), (detail['movieNight']['version'], detail['movieNight']['planRevision']))

    def test_conflicts_use_known_runtime_and_mark_unknown_ends(self):
        app = load_app('list-movie-nights-lambda', self.table)
        events = sys.modules['cmc_events']
        a = {'movieNightId': 'a', 'status': 'confirmed', 'movie': {'runtime': 120}, 'confirmedShowtime': {'startsAtUtc': '2099-01-01T18:00:00Z'}}
        b = {'movieNightId': 'b', 'status': 'confirmed', 'movie': {}, 'confirmedShowtime': {'startsAtUtc': '2099-01-01T20:00:00Z'}}
        self.assertEqual([], events.add_conflicts([a, b])[0]['conflicts'])
        a['movie']['runtime'] = None
        self.assertTrue(events.add_conflicts([a, b])[0]['conflicts'][0]['uncertain'])
        a['currentUserRsvp'] = {'status': 'going'}
        b['currentUserRsvp'] = {'status': 'not_going'}
        self.assertEqual([], events.add_conflicts([a, b], personal=True)[0]['conflicts'])

    def test_obsolete_reminders_and_outbox_are_not_delivered(self):
        self.confirm()
        self.confirm('s2', 2, 'change')
        sys.modules['pywebpush'] = types.SimpleNamespace(WebPushException=Exception, webpush=lambda **kwargs: None)
        app = load_app('notification-worker-lambda', self.table)
        with patch.object(app, 'deliver', return_value=True) as deliver:
            app.process_outbox()
            self.assertEqual(1, deliver.call_count)
            self.assertEqual(1, deliver.call_args.args[0]['calendarSequence'])
        app = load_app('notification-worker-lambda', self.table)
        with patch.object(app, 'deliver', return_value=True) as deliver, patch.object(app, 'now_iso', return_value='2100-01-01T00:00:00Z'):
            app.process_due()
            self.assertEqual(1, deliver.call_count)
            self.assertEqual(1, deliver.call_args.args[0]['calendarSequence'])

    def test_cancelled_night_suppresses_all_pending_reminders(self):
        self.confirm()
        self.call('cancel-movie-night-lambda', payload={'expectedVersion': 2})
        sys.modules['pywebpush'] = types.SimpleNamespace(WebPushException=Exception, webpush=lambda **kwargs: None)
        app = load_app('notification-worker-lambda', self.table)
        with patch.object(app, 'deliver', return_value=True) as deliver, patch.object(app, 'now_iso', return_value='2100-01-01T00:00:00Z'):
            app.process_due()
            deliver.assert_not_called()
        with patch.object(app, 'deliver', return_value=True) as deliver:
            app.process_outbox()
            self.assertEqual(['movie_night_cancelled'], [call.args[0]['notificationType'] for call in deliver.call_args_list])

    def test_parallel_ballots_and_rsvps_never_replace_another_event(self):
        self.table.items[('CLUB#one', 'MOVIE_NIGHT#a')].pop('votingClosedAt')
        self.night('b', status='voting').pop('votingClosedAt')
        self.night('plan', status='planning')
        self.showtime('b', 'b-show', '2099-02-01T18:00:00Z')
        for identifier, showtime in [('a', 's1'), ('b', 'b-show')]:
            result = self.call('submit-vote-lambda', identifier, {'rankings': [showtime]}, user='friend', method='PUT')
            self.assertEqual(200, result['statusCode'], result)
        self.table.items[('CLUB#one', 'MOVIE_NIGHT#a')]['votingClosedAt'] = '2020-01-01T00:00:00Z'
        self.confirm()
        self.call('update-rsvp-lambda', payload={'status': 'going', 'ticketStatus': 'purchased'}, user='friend', method='PUT')
        self.call('submit-vote-lambda', 'b', {'rankings': ['b-show']}, user='friend', method='PUT')
        self.call('cancel-movie-night-lambda', 'b', {'expectedVersion': 1})
        self.assertEqual(['s1'], self.table.items[('MOVIE_NIGHT#a', 'VOTE#friend')]['rankings'])
        self.assertEqual('going', self.table.items[('MOVIE_NIGHT#a', 'RSVP#friend')]['status'])
        self.assertEqual('planning', self.table.items[('CLUB#one', 'MOVIE_NIGHT#plan')]['status'])

    def test_stale_host_completion_does_not_complete_the_new_plan(self):
        self.confirm()
        self.confirm('s2', 2, 'change')
        self.assertEqual(409, self.call('complete-movie-night-lambda', payload={'expectedVersion': 2})['statusCode'])
        completed = self.call('complete-movie-night-lambda', payload={'expectedVersion': 3, 'idempotencyKey': 'complete'})
        self.assertEqual(200, completed['statusCode'])
        self.assertEqual(2, body(completed)['movieNight']['planRevision'])
        self.assertEqual(body(completed), body(self.call('complete-movie-night-lambda', payload={'expectedVersion': 3, 'idempotencyKey': 'complete'})))

    def test_current_revision_reminder_includes_members_with_stale_rsvps(self):
        self.confirm()
        self.call('update-rsvp-lambda', payload={'status': 'going'}, user='friend', method='PUT')
        self.confirm('s2', 2, 'change')
        sys.modules['pywebpush'] = types.SimpleNamespace(WebPushException=Exception, webpush=lambda **kwargs: None)
        app = load_app('notification-worker-lambda', self.table)
        recipients = app.eligible_members({'clubId': 'one', 'movieNightId': 'a', 'notificationType': 'rsvp_reminder', 'planRevision': 2})
        self.assertIn('friend', [m['userId'] for m in recipients])
        self.table.items[('CLUB#one', 'MEMBER#friend')]['status'] = 'removed'
        recipients = app.eligible_members({'clubId': 'one', 'movieNightId': 'a', 'notificationType': 'rsvp_reminder', 'planRevision': 2})
        self.assertNotIn('friend', [m['userId'] for m in recipients])

    def test_provider_work_is_discarded_after_cancellation_or_revision_change(self):
        app = load_app('gracenote-showtime-worker-lambda', self.table)
        message = {'movieNightId': 'a', 'clubId': 'one', 'eventVersion': 1}
        self.assertTrue(app.event_work_is_current(message))
        self.table.items[('CLUB#one', 'MOVIE_NIGHT#a')]['version'] = 2
        self.assertFalse(app.event_work_is_current(message))
        message.pop('eventVersion')
        self.table.items[('CLUB#one', 'MOVIE_NIGHT#a')]['status'] = 'cancelled'
        self.assertFalse(app.event_work_is_current(message))
        with patch.object(app, 'parse_message', return_value=message), patch.object(app, 'call_gracenote') as provider:
            app.process_record({'body': '{}'})
            provider.assert_not_called()

    def test_monitoring_removes_cancelled_event_work(self):
        self.table.items[('CLUB#one', 'MOVIE_NIGHT#a')]['status'] = 'cancelled'
        monitor = {'PK': 'SHOWTIME_MONITOR', 'SK': 'CHECK#2000-01-01T00:00:00Z#MOVIE_NIGHT#a', 'status': 'active', 'clubId': 'one', 'movieNightId': 'a'}
        self.table.put_item(Item=monitor)
        os.environ['SHOWTIME_REFRESH_QUEUE_URL'] = 'queue'
        app = load_app('showtime-monitor-lambda', self.table)
        self.assertEqual({'queued': 0}, app.handler({}, None))
        self.assertNotIn((monitor['PK'], monitor['SK']), self.table.items)


if __name__ == '__main__':
    unittest.main()
