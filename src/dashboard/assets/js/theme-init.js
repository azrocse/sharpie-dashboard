(function() {
            const hour = new Date().getHours();
            const theme = (hour >= 6 && hour < 19) ? 'light' : 'dark';
            document.documentElement.setAttribute('data-theme', theme);
        })();
