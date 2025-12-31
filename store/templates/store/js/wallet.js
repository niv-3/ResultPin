document.getElementById('purchase-form').addEventListener('submit', function(e) {
    e.preventDefault();

    const phone = document.getElementById('phone').value.trim();
    const paymentMethod = document.querySelector('input[name="payment_method"]:checked').value;
    const payButton = document.getElementById('pay-button');

    if (!/^0[789][01]\d{8}$/.test(phone)) {
        alert('Please enter a valid 11-digit Nigerian phone number');
        return;
    }

    payButton.disabled = true;
    payButton.innerHTML = 'Processing purchase...';

    fetch("{% url 'initiate_service_payment' plan.id %}", {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': getCsrfToken()
        },
        body: JSON.stringify({
            phone: phone,
            payment_method: paymentMethod
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.status) {
            if (paymentMethod === 'wallet') {
                // Instant success - no redirect needed
                alert('Purchase successful! Airtime delivered instantly.');
                window.location.reload();  // Or redirect to success page
            } else {
                // Card payment
                window.location.href = data.authorization_url;
            }
        } else {
            alert(data.message || 'Transaction failed. Try again.');
            payButton.disabled = false;
            payButton.innerHTML = 'Complete Purchase';
        }
    })
    .catch(err => {
        console.error(err);
        alert('Network error. Please try again.');
        payButton.disabled = false;
        payButton.innerHTML = 'Complete Purchase';
    });
});