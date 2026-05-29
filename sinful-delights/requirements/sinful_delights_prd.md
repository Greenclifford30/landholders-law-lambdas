**Summary**

Sinful Delights is a multi‑platform application for a private‑chef business that will let staff publish and price daily menus, control inventory, analyze sales, and let customers order meals, subscribe to weekly meal‑prep plans, or request catering—all from a single Flutter codebase deployed to Web, Android, and iOS. Flutter delivers near‑native performance without duplicating effort. The backend will run behind Amazon API Gateway, secured by API keys passed in the `X‑API‑Key` header, while customer authentication leverages social‑sign‑in via Firebase Auth.

## 1. Vision & Goals

- **Modern ordering** – replace ad‑hoc text‑message orders with an intuitive digital flow focused on same‑day pickup.  
- **Chef autonomy** – empower the chef to curate daily menus, set prices, and highlight specials in minutes—without overselling limited dishes.  
- **Recurring revenue** – grow predictable income through configurable meal‑prep subscriptions.  
- **Scalable operations** – collect analytics to guide menu decisions and capacity planning via real‑time dashboards.  

## 2. Target Users

| Persona                 | Needs                                                                     |
| ----------------------- | ------------------------------------------------------------------------- |
| **Chef/Admin**          | Fast menu & inventory editing, price control, visibility into sales & item popularity |
| **Daily‑Menu Customer** | Browse today’s choices, quick checkout for **pickup**, dietary filters     |
| **Subscriber**          | Choose plan, pause/skip weeks, manage billing                             |
| **Catering Client**     | Submit event details, receive invoice‑based deposit & status updates      |

## 3. Core Features

### 3.1 Daily Menu & Inventory Management
* CRUD menus and items with availability windows (date/time) and per-item flags such as “isSpecial”.
* **Predefined Menu Templates** – Admin can bundle a full set of items into a reusable template; apply a template to any calendar date in one click, then tweak individual items or prices as needed.
* **Stock count** per item with auto‑decrement on order placement; UI disables "Add to Cart" when count hits zero to prevent overselling.
* Optional bulk‑import from CSV/JSON and item cloning.
* Image upload to S3 via pre‑signed URL.

### 3.2 Pricing & Promotions
* Inline price editing with validation.
* Time‑boxed promo pricing and coupon codes.

### 3.3 Analytics Dashboard (MVP)
* Real‑time digital dashboards: daily gross sales, top items, average ticket, subscription churn, catering pipeline, etc.
* Charts powered by Firebase Analytics events streamed to BigQuery.

### 3.4 Meal‑Prep Subscription
* Plan attributes: meals per week, portion size, dietary tags.
* Recurring billing through Stripe Payment Sheet & webhooks.
* Customers can skip, pause, or modify plan up to the weekly cut‑off.

### 3.5 Catering Requests & Invoicing
* Wizard‑style form (event date, guest count, cuisine preferences, budget).
* Admin sees pipeline (New ► Quoted ► Invoiced ► Scheduled ► Completed).
* MVP sends **Stripe Invoice** for deposit; balance invoiced post‑event.

### 3.6 Customer Ordering Flow (Pickup‑Only MVP)
* Responsive product grid with imagery and "Add to Cart" CTA.
* Checkout collects pickup time‑slot; no delivery options in MVP (future integration TBD).
* One‑time payment via Stripe.

### 3.7 Push Notifications
* Firebase Cloud Messaging (FCM) to alert order‑ready, subscription reminders, and catering status changes.

## 4. Non‑Functional Requirements
* **Multi‑platform**: consistent UX on web, Android, iOS via Flutter 3.x.
* **Performance**: sub‑1 s initial load on modern phones; lazy‑load images.
* **Security**: HTTPS only; all API calls carry `X‑API‑Key`; Firebase Auth ID token passed via `Authorization` header; rate‑limit via Usage Plans.
* **Accessibility**: WCAG 2.1 AA colour & focus compliance.
* **Branding**: Primary colour **rgb(139, 0, 0)** (deep crimson) with black backgrounds/accents and grayscale shades for contrast. Apply provided horizontal & stacked logos per breakpoint.

## 5. Tech Stack

| Layer          | Selection | Rationale |
| -------------- | --------- | --------- |
| **UI**         | Flutter 3.x | Single codebase, hot‑reload |
| **State**      | Riverpod or Bloc | Scalable testable state |
| **Auth**       | Firebase Auth (Google, Apple, Facebook) for customers; API Key for service‑to‑service |
| **Networking** | `dio` package with interceptors for ID token + API key |
| **Backend**    | AWS Lambda behind API Gateway |
| **Payments**   | `flutter_stripe` SDK for one‑time & recurring; Stripe **Invoices** API for catering deposits |
| **Analytics**  | Firebase Analytics + BigQuery export |
| **Push**       | Firebase Cloud Messaging |
| **CI/CD**      | GitHub Actions → Firebase App Distribution / TestFlight / Play Store |
| **IaC**        | Terraform |

## 6. Data Model (High‑Level)

| Entity              | Key Fields |
| ------------------- | ---------- |
| **Menu**            | `menuId`, `date`, `title`, `isActive` |
| **MenuItem**        | `itemId`, `menuId`, `name`, `description`, `imageUrl`, `price`, `stockQty`, `isSpecial` |
| **PredefinedMenu**  | `templateId`, `name`, `items[]`, `createdAt` |
| **Order**           | `orderId`, `userId`, `items[]`, `total`, `status`, `pickupSlot`, `placedAt` |
| **Subscription**    | `subscriptionId`, `userId`, `plan`, `nextDelivery`, `status`, `skipDates[]` |
| **CateringRequest** | `requestId`, `userId`, `eventDate`, `guestCount`, `status`, `depositInvoiceId`, `quoteAmount` |

## 7. API Design (Key Endpoints)

| Method | Path | Secured | Purpose |
| ------ | ---- | ------- | ------- |
| GET  | `/v1/menu/today`         | API Key + ID Token | Fetch today’s menu |
| POST | `/v1/order`              | API Key + ID Token | Place pickup order |
| GET  | `/v1/subscription`       | API Key + ID Token | Get user subscription |
| POST | `/v1/subscription`       | API Key + ID Token | Create/modify plan |
| POST | `/v1/catering`           | API Key + ID Token | Submit catering request |
| **Admin** | | | |
| GET  | `/v1/admin/analytics`    | Admin Key | Dashboard metrics |
| POST | `/v1/admin/menu`         | Admin Key | Create/Update menu & items |
| POST | `/v1/admin/inventory`    | Admin Key | Adjust stock levels |

## 8. Security & Compliance
1. Enforce API Gateway Usage Plans with throttling.
2. Firebase Auth ID token validated by custom Lambda authorizer.
3. Stripe handles PCI; no card data stored.
4. Monthly API key rotation & CloudWatch anomaly alerts.

## 9. Observability & Analytics
* Firebase Analytics custom events: `view_menu`, `add_to_cart`, `checkout_started`, `subscription_created`, `order_ready_push_sent`, etc.
* CloudWatch Logs & X‑Ray for Lambda traces.

## 10. Development Phases

| Sprint | Deliverables |
| ------ | ------------ |
| **0 – Setup** | Repo, CI/CD, Terraform baseline, brand assets integration |
| **1 – Menu, Inventory & Ordering MVP** | Flutter UI (pickup flow), stock enforcement, mock backend |
| **2 – API, Payments & Auth** | API Gateway + Lambda, Stripe one‑time payments, Firebase Auth social sign‑in |
| **3 – Subscriptions** | Plan UI, recurring billing, skip/pause functionality |
| **4 – Catering & Invoicing** | Catering wizard, Stripe invoice deposit flow, admin pipeline |
| **5 – Analytics & Push** | Real‑time dashboards, Firebase Cloud Messaging |
| **6 – Hardening & Launch** | Load tests, security review, store submissions |

## 11. Acceptance Criteria (Updated Excerpts)
* Chef cannot oversell: once `stockQty` hits 0, the item is hidden or disabled for customers.  
* Customer completes pickup order in ≤ 5 steps and receives push notification when order is ready.  
* Catering client receives invoice within 1 business day of quote approval.

## 12. Risks & Mitigations
| Risk | Likelihood | Mitigation |
| ---- | ---------- | ---------- |
| API key leakage | Medium | Rotate keys; monitor spikes |
| Stock mis‑counts | Medium | Atomic decrement & daily stock audit |
| Push notification deliverability | Low | Fallback to email alerts |

## 13. Remaining Open Questions
1. **Future Delivery** – Which courier integration is preferred when we expand beyond pickup?  
2. **Reporting Exports** – Are CSV/PDF exports needed post‑MVP?  
3. **Loyalty/Rewards** – Any appetite for points or referral tracking later?  

---

### Next Steps
Confirm remaining open questions and provide logo files so we can embed assets and finalise the design system.
