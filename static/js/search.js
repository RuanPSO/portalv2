document.addEventListener('DOMContentLoaded', () => {
  const searchBox = document.getElementById('searchBox');
  if (!searchBox) return;

  let timeout = null;

  searchBox.addEventListener('input', () => {
    clearTimeout(timeout);

    timeout = setTimeout(() => {
      const term = searchBox.value.toLowerCase().trim();
      let encontrados = 0;

      document.querySelectorAll('[data-search]').forEach(el => {
        const text = el.dataset.search.toLowerCase();

        if (text.includes(term)) {
          el.style.display = '';
          encontrados++;

          // 🔥 highlight simples
          const original = el.dataset.original || el.innerText;
          el.dataset.original = original;

          if (term) {
            const regex = new RegExp(`(${term})`, 'gi');
            el.innerHTML = original.replace(regex, '<mark>$1</mark>');
          } else {
            el.innerHTML = original;
          }

        } else {
          el.style.display = 'none';
        }
      });

      // 👇 mensagem opcional
      let emptyMsg = document.getElementById('noResults');

      if (!emptyMsg) {
        emptyMsg = document.createElement('div');
        emptyMsg.id = 'noResults';
        emptyMsg.style.padding = '10px';
        emptyMsg.style.color = '#999';
        searchBox.parentNode.appendChild(emptyMsg);
      }

      emptyMsg.innerText = encontrados === 0 ? "Nenhum resultado" : "";

    }, 200); // debounce
  });
});