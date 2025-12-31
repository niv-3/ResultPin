document.getElementById("purchase-form").addEventListener("submit", function (e) {
    e.preventDefault();

    const phoneInput = document.getElementById("phone");
    const paymentMethodInput = document.querySelector('input[name="payment_method"]:checked');
    const payButton = document.getElementById("pay-button");

    if (!phoneInput || !paymentMethodInput) {
        alert("Missing required fields");
        return;
    }

    const phone = phoneInput.value.trim();
    const paymentMethod = paymentMethodInput.value;

    if (!/^(0[789][01]\d{8}|(\+234)[789][01]\d{8})$/.test(phone)) {
        alert("Enter a valid Nigerian phone number");
        return;
    }

    payButton.disabled = true;
    payButton.textContent = "Processing...";

    fetch(payButton.dataset.payUrl, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": getCSRFToken(),
        },
        body: JSON.stringify({
            phone: phone,
            payment_method: paymentMethod,
        }),
    })
        .then((res) => res.json())
        .then((data) => {
            if (!data.status) {
                throw new Error(data.message || "Transaction failed");
            }

            // Card payment
            if (data.authorization_url) {
                window.location.href = data.authorization_url;
                return;
            }

            // Wallet payment (instant)
            alert(data.message || "Purchase successful");
            window.location.href = "/payment-success/";
        })
        .catch((err) => {
            alert(err.message || "Network error");
            payButton.disabled = false;
            payButton.textContent = "Complete Purchase";
        });
});

// -----------------------
// CSRF helper
// -----------------------
function getCSRFToken() {
    const name = "csrftoken=";
    const cookies = document.cookie.split(";");

    for (let cookie of cookies) {
        cookie = cookie.trim();
        if (cookie.startsWith(name)) {
            return cookie.substring(name.length);
        }
    }
    return "";
}
