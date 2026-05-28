// Inject the UI
const widget = document.createElement('div');
widget.id = 'motel-scanner-widget';
widget.innerHTML = `
    <span class="scanner-icon">🪪</span>
    <span class="scanner-text">Scan Guest ID</span>
`;
document.body.appendChild(widget);

const textElement = widget.querySelector('.scanner-text');

// Helper function to safely fill fields and trigger the PMS's built-in validation
function fillAndTrigger(elementId, value) {
    const el = document.getElementById(elementId);
    if (el && value) {
        el.value = value;
        // Tell the website the field was typed in so it doesn't throw a "Required" error
        el.dispatchEvent(new Event('change', { bubbles: true }));
        el.dispatchEvent(new Event('keyup', { bubbles: true }));
        return true;
    }

    console.warn('Motel scanner could not fill field:', {
        elementId,
        found: Boolean(el),
        hasValue: Boolean(value)
    });
    return false;
}

// Handle the click
widget.addEventListener('click', async () => {
    widget.classList.add('scanning');
    widget.classList.remove('success', 'error');
    textElement.innerText = 'Initializing Scanner...';

    try {
        const response = await fetch('http://localhost:5000/scan', {
            method: 'POST'
        });

        const result = await response.json().catch(() => ({
            status: 'error',
            message: `Scanner server returned HTTP ${response.status}`
        }));

        if (response.ok && result.status === 'success') {
            widget.classList.remove('scanning');
            widget.classList.add('success');
            textElement.innerText = 'ID Captured!';
            widget.querySelector('.scanner-icon').innerText = '✓';

            // Mapped exactly to the WebCheckINN PMS HTML
            const filledFields = [
                fillAndTrigger('guestFirstName', result.data.firstName),
                fillAndTrigger('guestLastName', result.data.lastName),
                fillAndTrigger('guestHomeAddressOne', result.data.address),
                fillAndTrigger('guestHomeCity', result.data.city),
                fillAndTrigger('homeState', result.data.state),
                fillAndTrigger('guestHomeZip', result.data.zip),
                fillAndTrigger('guestPersonalId', result.data.licenseNumber)
            ];

            if (filledFields.some((filled) => !filled)) {
                console.warn('Motel scanner decoded the ID but not every PMS field was filled.');
            }
            
        } else {
            throw new Error(result.message || result.errorCode || 'Scan failed');
        }
    } catch (error) {
        widget.classList.remove('scanning');
        widget.classList.add('error');
        textElement.innerText = 'Scan Failed';
        widget.querySelector('.scanner-icon').innerText = '✕';
        console.error("Scanner Error:", error);
    }
    
    // Reset UI after 4 seconds
    setTimeout(() => {
        widget.classList.remove('scanning', 'success', 'error');
        textElement.innerText = 'Scan Guest ID';
        widget.querySelector('.scanner-icon').innerText = '🪪';
    }, 4000);
});
