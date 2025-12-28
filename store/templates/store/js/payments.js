function startPayment(itemType, itemId) {
    const phoneInput = document.getElementById("phone");

    if (!phoneInput || !phoneInput.value) {
        alert("Please enter a phone number");
        return;
    }

    fetch("/payments/start/", {
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": getCSRFToken()
        },
        body: JSON.stringify({
            type: itemType,   // "product" or "service"
            id: itemId,
            phone: phoneInput.value
        })
    })
    .then(res => res.json())
    .then(data => {
        if (data.status) {
            window.location.href = data.data.authorization_url;
        } else {
            alert(data.message || "Payment failed");
        }
    })
    .catch(() => alert("Network error. Try again."));
}


// -----------------------
// CSRF helper
// -----------------------
function getCSRFToken() {
    const name = "csrftoken";
    const cookies = document.cookie.split(";");

    for (let cookie of cookies) {
        cookie = cookie.trim();
        if (cookie.startsWith(name + "=")) {
            return cookie.substring(name.length + 1);
        }
    }
    return "";
}
