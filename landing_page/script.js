document.addEventListener('DOMContentLoaded', () => {
    // Fade-in animation on scroll
    const faders = document.querySelectorAll('.fade-in');

    const appearOptions = {
        threshold: 0.15,
        rootMargin: "0px 0px -50px 0px"
    };

    const appearOnScroll = new IntersectionObserver(function(
        entries,
        observer
    ) {
        entries.forEach(entry => {
            if (!entry.isIntersecting) {
                return;
            } else {
                entry.target.classList.add('appear');
                observer.unobserve(entry.target);
            }
        });
    },
    appearOptions);

    faders.forEach(fader => {
        appearOnScroll.observe(fader);
    });
    
    // Trigger the observer manually for the hero section on load
    setTimeout(() => {
        document.querySelector('.hero').classList.add('appear');
    }, 100);

    // Chat Animation Logic
    const aiResponse = document.getElementById('ai-response');
    if (aiResponse) {
        setTimeout(() => {
            aiResponse.classList.add('visible');
            // Remove typing indicator after 2 seconds and add text
            setTimeout(() => {
                aiResponse.innerHTML = "Según el manual técnico (Pág 14), el par de apriete nominal para el motor V8 en operación continua es de <strong>45 Nm</strong>.<br><br><small><em>Fuente: Manual_Mantenimiento_V8.pdf</em></small>";
            }, 2500);
        }, 1200);
    }

    // Form Handling
    const form = document.getElementById('privai-form');
    const result = document.getElementById('form-status');

    if (form) {
        form.addEventListener('submit', function(e) {
            e.preventDefault();
            const formData = new FormData(form);
            const object = Object.fromEntries(formData);
            const json = JSON.stringify(object);
            
            // Check if Access Key was configured
            if (object.access_key === 'TU_ACCESS_KEY') {
                result.innerHTML = "Configuración pendiente. El administrador debe añadir la Access Key.";
                result.className = "form-status error";
                return;
            }

            result.innerHTML = "Enviando solicitud...";
            result.className = "form-status";

            fetch('https://api.web3forms.com/submit', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                    'Accept': 'application/json'
                },
                body: json
            })
            .then(async (response) => {
                let json = await response.json();
                if (response.status == 200) {
                    result.innerHTML = "¡Solicitud enviada! Nos pondremos en contacto muy pronto.";
                    result.className = "form-status success";
                    form.reset();
                } else {
                    result.innerHTML = json.message;
                    result.className = "form-status error";
                }
            })
            .catch(error => {
                result.innerHTML = "Hubo un error al enviar tu solicitud.";
                result.className = "form-status error";
            })
            .then(function() {
                setTimeout(() => {
                    result.innerHTML = "";
                    result.className = "form-status";
                }, 5000);
            });
        });
    }
});
