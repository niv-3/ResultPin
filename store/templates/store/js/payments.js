function startPayment(planId, paymentMethod = "card") {
    const phoneInput = document.getElementById("phone");

    if (!phoneInput || !phoneInput.value.trim()) {
        alert("Please enter a phone number");
        return;
    }

    fetch(`/service/pay/${planId}/`, {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": getCSRFToken(),
        },
        body: JSON.stringify({
            phone: phoneInput.value.trim(),
            payment_method: paymentMethod, // "card" or "wallet"
        }),
    })
        .then((res) => res.json())
        .then((data) => {
            if (!data.status) {
                alert(data.message || "Payment failed");
                return;
            }

            // Card payment → redirect to Paystack
            if (data.authorization_url) {
                window.location.href = data.authorization_url;
                return;
            }

            // Wallet payment → already completed
            alert(data.message || "Payment successful");
            window.location.href = "/payment/success/";
        })
        .catch(() => {
            alert("Network error. Try again.");
        });
}

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
