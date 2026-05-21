# Example GUIdebuger BugReport

**Bug ID:** BUG-SAMPLE-001

**Application:** DemoShop

**Package:** com.example.demoshop

**Activity:** com.example.demoshop.CartActivity

**Category:** cross-page data inconsistency

**Severity:** medium

## Summary

After adding one item to the cart and returning from the product details page,
the cart badge still shows zero items while the cart page contains the selected
item.

## Reproduction Steps

1. Open the product list.
2. Select the product named "Wireless Mouse".
3. Tap "Add to cart".
4. Return to the product list.
5. Observe the cart badge and open the cart page.

## Evidence

- The Explorer recorded the add-to-cart action and the following navigation.
- The Supervisor confirmed that the cart badge and cart contents describe
  inconsistent states.
- Screenshots are omitted from this compact sample.

## Supervisor Review

Confirmed. The candidate report compares two user-visible states that should be
consistent after a successful add-to-cart operation.
