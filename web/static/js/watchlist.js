/* Browser-only state. No server identity, prices, names or personal labels. */
(() => {
    const key = 'stock-tracker-watchlist';
    const defaults = JSON.parse(document.querySelector('#watchlist-defaults').textContent);
    let symbols = [],
        warning = '';
    const listeners = new Set();
    const normalize = value => value.trim().toUpperCase().replaceAll('.', '-');

    function validate(value) {
        if (!value || typeof value !== 'object' || Array.isArray(value) ||
            Object.keys(value).sort().join(',') !== 'symbols,version' || value.version !== 1 ||
            !Array.isArray(value.symbols) || value.symbols.length > 100 ||
            value.symbols.some(s => typeof s !== 'string' || s.length > 15 || !/^[A-Z^][A-Z0-9.^-]{0,14}$/.test(s.trim().toUpperCase()))) {
            throw Error('format');
        }
        const unique = [...new Set(value.symbols.map(normalize))];
        return {
            symbols: unique,
            duplicates: value.symbols.length - unique.length
        };
    }

    function emit() {
        listeners.forEach(fn => fn());
    }

    function persist() {
        try {
            localStorage.setItem(key, JSON.stringify({
                version: 1,
                symbols
            }));
            warning = '';
        } catch {
            warning = 'storage';
        }
        emit();
    }

    function read(initial = false) {
        let raw;
        try {
            raw = localStorage.getItem(key);
        } catch {
            symbols = initial ? [...defaults.symbols] : symbols;
            warning = 'storage';
            emit();
            return;
        }
        try {
            if (raw === null) {
                symbols = initial ? [...defaults.symbols] : [];
                warning = initial ? '' : 'removed';
                if (initial) persist();
            } else {
                symbols = validate(JSON.parse(raw)).symbols;
                warning = '';
            }
        } catch {
            symbols = [];
            warning = 'invalid';
        }
        emit();
    }
    window.Favorites = {
        get: () => [...symbols],
        warning: () => warning,
        validate,
        subscribe: fn => {
            listeners.add(fn);
            return () => listeners.delete(fn);
        },
        replace: values => {
            symbols = validate({
                version: 1,
                symbols: values
            }).symbols;
            persist();
        },
        toggle: symbol => {
            symbol = normalize(symbol);
            window.Favorites.replace(symbols.includes(symbol) ? symbols.filter(s => s !== symbol) : [...symbols, symbol]);
        },
        move: (symbol, delta) => {
            const i = symbols.indexOf(normalize(symbol)),
                next = i + delta;
            if (i < 0 || next < 0 || next >= symbols.length) return;
            [symbols[i], symbols[next]] = [symbols[next], symbols[i]];
            persist();
        },
        defaults: () => [...defaults.symbols]
    };
    window.addEventListener('storage', event => {
        if (event.key === key || event.key === null) read();
    });
    read(true);
})();
