#!/usr/bin/env python3
"""
BLOCK 7 Verification Script
============================
Verifies that the billing integration is properly configured.
"""

import sys
import os
from pathlib import Path

# Color codes for output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'

def print_header(text):
    print(f"\n{BLUE}{'='*60}{RESET}")
    print(f"{BLUE}{text:^60}{RESET}")
    print(f"{BLUE}{'='*60}{RESET}\n")

def print_success(text):
    print(f"{GREEN}✓{RESET} {text}")

def print_error(text):
    print(f"{RED}✗{RESET} {text}")

def print_warning(text):
    print(f"{YELLOW}⚠{RESET} {text}")

def check_file_exists(filepath, description):
    """Check if a file exists."""
    if Path(filepath).exists():
        print_success(f"{description} exists")
        return True
    else:
        print_error(f"{description} missing: {filepath}")
        return False

def check_file_contains(filepath, search_text, description):
    """Check if a file contains specific text."""
    try:
        with open(filepath, 'r') as f:
            content = f.read()
            if search_text in content:
                print_success(f"{description}")
                return True
            else:
                print_error(f"{description} - not found in {filepath}")
                return False
    except Exception as e:
        print_error(f"Error reading {filepath}: {e}")
        return False

def check_env_var(var_name, required=True):
    """Check if environment variable is set."""
    value = os.getenv(var_name)
    if value:
        # Mask sensitive values
        if 'KEY' in var_name or 'SECRET' in var_name:
            masked = value[:10] + '...' if len(value) > 10 else '***'
            print_success(f"{var_name} is set: {masked}")
        else:
            print_success(f"{var_name} is set: {value}")
        return True
    else:
        if required:
            print_error(f"{var_name} is not set")
        else:
            print_warning(f"{var_name} is not set (optional)")
        return not required

def main():
    print_header("BLOCK 7: Billing Integration Verification")
    
    all_passed = True
    
    # Set base path
    base_path = Path(__file__).parent
    api_path = base_path / "services" / "api"
    
    # 1. Check files exist
    print_header("1. File Structure")
    
    files_to_check = [
        (api_path / "app/services/stripe_service.py", "StripeService"),
        (api_path / "app/routers/billing.py", "Billing Router"),
        (api_path / "app/schemas/billing.py", "Billing Schemas"),
        (api_path / "alembic/versions/009_billing_integration.py", "Migration 009"),
        (base_path / "docs/BLOCK_7_COMPLETE.md", "Documentation"),
        (base_path / "BLOCK_7_SUMMARY.md", "Deployment Guide"),
    ]
    
    for filepath, description in files_to_check:
        if not check_file_exists(filepath, description):
            all_passed = False
    
    # 2. Check User model changes
    print_header("2. Database Model Changes")
    
    user_model_path = api_path / "app/db/models/user.py"
    model_checks = [
        ("stripe_customer_id", "stripe_customer_id field added to User model"),
        ("stripe_subscription_id", "stripe_subscription_id field added to User model"),
        ("subscription_status", "subscription_status field added to User model"),
        ("current_period_end", "current_period_end field added to User model"),
        ("is_subscribed", "is_subscribed property added to User model"),
    ]
    
    for search_text, description in model_checks:
        if not check_file_contains(user_model_path, search_text, description):
            all_passed = False
    
    # 3. Check configuration
    print_header("3. Configuration")
    
    config_path = api_path / "app/core/config.py"
    config_checks = [
        ("stripe_secret_key", "stripe_secret_key setting"),
        ("stripe_publishable_key", "stripe_publishable_key setting"),
        ("stripe_webhook_secret", "stripe_webhook_secret setting"),
        ("stripe_price_basic_monthly", "Price ID settings"),
    ]
    
    for search_text, description in config_checks:
        if not check_file_contains(config_path, search_text, description):
            all_passed = False
    
    # 4. Check main.py registration
    print_header("4. Router Registration")
    
    main_path = api_path / "app/main.py"
    main_checks = [
        ("billing_router", "Billing router imported"),
        ("include_router(billing_router)", "Billing router registered"),
        ("0.9.0", "Version updated to 0.9.0"),
    ]
    
    for search_text, description in main_checks:
        if not check_file_contains(main_path, search_text, description):
            all_passed = False
    
    # 5. Check metrics
    print_header("5. Revenue Metrics")
    
    metrics_path = api_path / "app/financial/financial_metrics.py"
    metrics_checks = [
        ("revenue_total", "revenue_total metric"),
        ("active_subscriptions_total", "active_subscriptions_total metric"),
        ("mrr", "MRR metric"),
        ("subscription_events_total", "subscription_events_total metric"),
    ]
    
    for search_text, description in metrics_checks:
        if not check_file_contains(metrics_path, search_text, description):
            all_passed = False
    
    # 6. Check dependencies
    print_header("6. Dependencies")
    
    requirements_path = api_path / "requirements.txt"
    if not check_file_contains(requirements_path, "stripe", "stripe package added"):
        all_passed = False
    
    # Try to import stripe
    try:
        import stripe
        print_success(f"stripe package installed (version {stripe.__version__})")
    except ImportError:
        print_error("stripe package not installed")
        print_warning("Run: pip install stripe==8.2.0")
        all_passed = False
    
    # 7. Check environment variables (optional - may not be set yet)
    print_header("7. Environment Variables (Optional)")
    
    print_warning("These may not be set yet - that's OK for development")
    
    env_vars = [
        ("STRIPE_SECRET_KEY", True),
        ("STRIPE_PUBLISHABLE_KEY", False),
        ("STRIPE_WEBHOOK_SECRET", True),
        ("STRIPE_PRICE_BASIC_MONTHLY", False),
        ("STRIPE_PRICE_PRO_MONTHLY", False),
        ("STRIPE_PRICE_ENTERPRISE_MONTHLY", False),
    ]
    
    env_set = 0
    for var_name, required in env_vars:
        if check_env_var(var_name, required=False):
            env_set += 1
    
    if env_set == 0:
        print_warning("No Stripe environment variables set")
        print_warning("This is OK for development - configure before production")
    
    # 8. Summary
    print_header("Verification Summary")
    
    if all_passed:
        print_success("All core checks passed! ✓")
        print(f"\n{GREEN}BLOCK 7 is properly installed.{RESET}")
        print(f"\n{YELLOW}Next steps:{RESET}")
        print("  1. Run migration: alembic upgrade head")
        print("  2. Configure Stripe (see BLOCK_7_SUMMARY.md)")
        print("  3. Set environment variables")
        print("  4. Restart API server")
        print("  5. Test with: stripe trigger checkout.session.completed")
    else:
        print_error("Some checks failed!")
        print(f"\n{RED}Please review the errors above.{RESET}")
        print(f"\n{YELLOW}See docs/BLOCK_7_COMPLETE.md for details.{RESET}")
        sys.exit(1)
    
    print()

if __name__ == "__main__":
    main()
