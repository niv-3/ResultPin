document.getElementById("fund-form").addEventListener("submit", function (e) {
    e.preventDefault();

    const amount = document.getElementById("amount").value;

    if (!amount || amount < 100) {
        alert("Minimum funding amount is ₦100");
        return;
    }

    // Show loading
    const button = e.target.querySelector("button[type='submit']");
    button.disabled = true;
    button.innerHTML = "Processing...";

    fetch("{% url 'wallet_fund_init' %}", {  // Use correct URL
        method: "POST",
        headers: {
            "Content-Type": "application/json",
            "X-CSRFToken": getCSRFToken(),
        },
        body: JSON.stringify({ amount }),
    })
    .then((res) => res.json())
    .then((data) => {
        if (data.status) {
            // SAME AS YOUR WORKING payment.js — Redirect to Paystack checkout
            window.location.href = data.data.authorization_url;
        } else {
            alert(data.message || "Unable to start payment");
            button.disabled = false;
            button.innerHTML = "Fund Now with Paystack";
        }
    })
    .catch((err) => {
        console.error(err);
        alert("Network error. Please try again.");
        button.disabled = false;
        button.innerHTML = "Fund Now with Paystack";
    });
});