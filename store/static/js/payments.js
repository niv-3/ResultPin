// ==============================
// Unified Service Payment Starter
// ==============================
function submitPurchase() {
    if (submitting || !currentPlan) return;

    const phone = document.getElementById("modal-phone").value.trim();
    const method = document.querySelector('input[name="payment_method"]:checked');

    if (!phone || !/^0\d{10}$/.test(phone)) {
        alert("Please enter a valid 11-digit phone number");
        return;
    }
    if (!method) {
        alert("Please select a payment method");
        return;
    }

    submitting = true;
    const btn = document.getElementById("pay-btn");
    btn.disabled = true;
    btn.textContent = "Processing...";

    // ────────────────────────────────────────────────
    // Use categorySlug from template (dynamic & correct)
    // This matches the new <slug:category_slug> URL pattern
    // ────────────────────────────────────────────────
    const categorySlug = currentPlan.categorySlug || currentPlan.serviceType; // fallback if not set yet

    if (!categorySlug) {
        alert("Service category not configured. Contact support.");
        submitting = false;
        btn.disabled = false;
        btn.textContent = "Complete Purchase";
        return;
    }

    const url = `/service/pay/${categorySlug}/${currentPlan.planId}/`;

    console.log("Sending purchase request to:", url); // ← helpful for debugging

    fetch(url, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": document.querySelector('[name=csrfmiddlewaretoken]').value
        },
        body: JSON.stringify({
            phone: phone,                    // standardized key
            payment_method: method.value
            // Note: provider_id and amount not needed — backend gets them from plan_id
        })
    })
    .then(r => {
        if (!r.ok) {
            throw new Error(`HTTP error! Status: ${r.status}`);
        }
        return r.json();
    })
    .then(data => {
        if (data.status === true) {
            if (data.authorization_url) {
                window.location.href = data.authorization_url;
            } else {
                window.location.href = data.redirect_url || "/payment/success/";
            }
        } else {
            alert(data.message || "Transaction failed");
        }
    })
    .catch(err => {
        console.error("Purchase error:", err);
        alert("Network error or service unavailable. Please try again.");
    })
    .finally(() => {
        submitting = false;
        btn.disabled = false;
        btn.textContent = "Complete Purchase";
    });
}