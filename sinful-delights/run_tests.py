#!/usr/bin/env python3
"""
Test runner script for Sinful Delights API
"""
import subprocess
import sys
import os
from pathlib import Path


def install_dependencies():
    """Install test dependencies"""
    print("Installing test dependencies...")
    try:
        subprocess.run([
            sys.executable, "-m", "pip", "install", "-r", "requirements-test.txt"
        ], check=True, cwd=Path(__file__).parent)
        print("✓ Dependencies installed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"✗ Failed to install dependencies: {e}")
        return False


def run_tests():
    """Run pytest with coverage"""
    print("\nRunning tests with coverage...")
    
    # Set PYTHONPATH to include current directory
    env = os.environ.copy()
    env['PYTHONPATH'] = str(Path(__file__).parent)
    
    try:
        result = subprocess.run([
            sys.executable, "-m", "pytest", 
            "-v",
            "--tb=short", 
            "--cov=shared",
            "--cov-report=term-missing",
            "--cov-report=html:htmlcov",
            "tests/"
        ], cwd=Path(__file__).parent, env=env)
        
        return result.returncode == 0
    except FileNotFoundError:
        print("✗ pytest not found. Please install pytest first.")
        return False


def run_specific_tests():
    """Run specific test categories"""
    test_commands = [
        (["python", "-m", "pytest", "tests/test_shared_models.py", "-v"], "Model validation tests"),
        (["python", "-m", "pytest", "tests/test_get_menu_today.py", "-v"], "GET /menu/today tests"),
        (["python", "-m", "pytest", "tests/test_post_order.py", "-v"], "POST /order tests"),
    ]
    
    results = {}
    env = os.environ.copy()
    env['PYTHONPATH'] = str(Path(__file__).parent)
    
    for command, description in test_commands:
        print(f"\n{'='*60}")
        print(f"Running {description}")
        print('='*60)
        
        try:
            result = subprocess.run(command, cwd=Path(__file__).parent, env=env)
            results[description] = result.returncode == 0
        except Exception as e:
            print(f"✗ Failed to run {description}: {e}")
            results[description] = False
    
    return results


def main():
    """Main test runner"""
    print("Sinful Delights API - Test Suite")
    print("="*50)
    
    # Install dependencies first
    if not install_dependencies():
        print("\nSkipping tests due to dependency installation failure.")
        return False
    
    # Run all tests with coverage
    success = run_tests()
    
    if success:
        print("\n✓ All tests passed!")
        print("\nCoverage report generated in htmlcov/ directory")
    else:
        print("\n✗ Some tests failed.")
    
    # Run specific test categories for detailed output
    print("\n" + "="*60)
    print("DETAILED TEST RESULTS BY CATEGORY")
    print("="*60)
    
    category_results = run_specific_tests()
    
    print("\n" + "="*60)
    print("SUMMARY")
    print("="*60)
    
    for category, passed in category_results.items():
        status = "✓ PASSED" if passed else "✗ FAILED"
        print(f"{status:<10} {category}")
    
    overall_success = success and all(category_results.values())
    
    if overall_success:
        print(f"\n🎉 All test categories passed!")
    else:
        print(f"\n⚠️  Some tests failed. Check the output above for details.")
    
    return overall_success


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)