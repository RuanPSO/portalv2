// static/js/hosts_group_styles.js

// Sistema de estilização e animações para cards de hosts
const HostStyler = {
  // Cores por tipo de status
  colors: {
    up: {
      border: '#10B981',
      shadow: '0 4px 6px -1px rgba(16, 185, 129, 0.1), 0 2px 4px -1px rgba(16, 185, 129, 0.06)',
      badge: '#D1FAE5',
      badgeText: '#065F46'
    },
    down: {
      border: '#EF4444',
      shadow: '0 4px 6px -1px rgba(239, 68, 68, 0.1), 0 2px 4px -1px rgba(239, 68, 68, 0.06)',
      badge: '#FEE2E2',
      badgeText: '#991B1B'
    },
    unknown: {
      border: '#9CA3AF',
      shadow: '0 1px 3px 0 rgba(0, 0, 0, 0.1), 0 1px 2px 0 rgba(0, 0, 0, 0.06)',
      badge: '#F3F4F6',
      badgeText: '#374151'
    },
    warning: {
      border: '#F59E0B',
      shadow: '0 4px 6px -1px rgba(245, 158, 11, 0.1), 0 2px 4px -1px rgba(245, 158, 11, 0.06)',
      badge: '#FEF3C7',
      badgeText: '#92400E'
    }
  },

  // Aplica estilo base a todos os cards
  applyBaseStyles() {
    document.querySelectorAll('.host-card').forEach(card => {
      card.style.transition = 'all 0.3s ease';
      card.style.border = '2px solid #E5E7EB';
      card.style.position = 'relative';
      card.style.overflow = 'hidden';
      
      // Efeito hover
      card.addEventListener('mouseenter', () => {
        card.style.transform = 'translateY(-2px)';
        card.style.boxShadow = '0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -2px rgba(0, 0, 0, 0.05)';
      });
      
      card.addEventListener('mouseleave', () => {
        card.style.transform = 'translateY(0)';
        card.style.boxShadow = '0 1px 3px 0 rgba(0, 0, 0, 0.1), 0 1px 2px 0 rgba(0, 0, 0, 0.06)';
      });
    });
  },

  // Atualiza estilo baseado no status do host
  updateCardStyle(hostid, status) {
    const card = document.querySelector(`.host-card[data-hostid="${hostid}"]`);
    if (!card) return;
    
    const style = this.colors[status.toLowerCase()] || this.colors.unknown;
    
    card.style.borderLeft = `4px solid ${style.border}`;
    card.style.boxShadow = style.shadow;
    
    // Adiciona badge de status
    this.addStatusBadge(card, status, style);
  },

  // Adiciona badge de status no canto superior direito
  addStatusBadge(card, status, style) {
    let badge = card.querySelector('.status-badge');
    if (!badge) {
      badge = document.createElement('div');
      badge.className = 'status-badge';
      badge.style.cssText = `
        position: absolute;
        top: 8px;
        right: 8px;
        padding: 2px 8px;
        border-radius: 9999px;
        font-size: 10px;
        font-weight: 700;
        text-transform: uppercase;
        letter-spacing: 0.5px;
        z-index: 10;
        background: ${style.badge};
        color: ${style.badgeText};
      `;
      card.style.position = 'relative';
      card.appendChild(badge);
    }
    badge.textContent = status;
  },

  // Anima barra de progresso
  animateProgressBar(barElement, value, color) {
    if (!barElement) return;
    
    barElement.style.transition = 'width 0.6s cubic-bezier(0.4, 0, 0.2, 1)';
    barElement.style.width = `${value}%`;
    barElement.style.background = color;
  },

  // Formata números grandes
  formatBytes(bytes) {
    if (bytes === 0) return '0 Bytes';
    const k = 1024;
    const sizes = ['Bytes', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + ' ' + sizes[i];
  },

  // Cria tooltip informativo
  createTooltip(element, text) {
    element.setAttribute('title', text);
    element.style.cursor = 'help';
  },

  // Adiciona indicador de carregamento
  showLoading(element) {
    element.innerHTML = `
      <div class="loading-spinner">
        <svg class="animate-spin h-4 w-4 text-blue-600" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
          <circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"></circle>
          <path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
        </svg>
      </div>
    `;
  },

  // Adiciona ícones aos elementos
  addIcons() {
    // Sistema
    document.querySelectorAll('[id^="os-"]').forEach(el => {
      const parent = el.closest('p');
      if (parent) {
        const icon = document.createElement('span');
        icon.innerHTML = '💻 ';
        icon.style.marginRight = '4px';
        parent.insertBefore(icon, el);
      }
    });
    
    // IP
    document.querySelectorAll('[id^="ip-"]').forEach(el => {
      const parent = el.closest('p');
      if (parent) {
        const icon = document.createElement('span');
        icon.innerHTML = '🌐 ';
        icon.style.marginRight = '4px';
        parent.insertBefore(icon, el);
      }
    });
    
    // Porta
    document.querySelectorAll('[id^="porta-"]').forEach(el => {
      const parent = el.closest('p');
      if (parent) {
        const icon = document.createElement('span');
        icon.innerHTML = '🔌 ';
        icon.style.marginRight = '4px';
        parent.insertBefore(icon, el);
      }
    });
  },

  // Destaca host com alertas
  highlightAlerts(hostid, hasAlerts) {
    const card = document.querySelector(`.host-card[data-hostid="${hostid}"]`);
    if (card && hasAlerts) {
      card.style.animation = 'pulse 2s infinite';
      
      // Adiciona estilo de animação se não existir
      if (!document.querySelector('#pulse-animation')) {
        const style = document.createElement('style');
        style.id = 'pulse-animation';
        style.textContent = `
          @keyframes pulse {
            0%, 100% { box-shadow: 0 0 0 0 rgba(239, 68, 68, 0.7); }
            50% { box-shadow: 0 0 0 8px rgba(239, 68, 68, 0); }
          }
        `;
        document.head.appendChild(style);
      }
    }
  }
};

// Estilizador específico para o grupo
const GroupStyler = {
  // Configura layout do grid
  setupGrid() {
    const container = document.getElementById('hostsContainer');
    if (container) {
      container.style.display = 'grid';
      container.style.gap = '1.5rem';
      container.style.padding = '1rem 0';
    }
  },

  // Adiciona cabeçalho estilizado
  styleHeader(grupo) {
    const header = document.querySelector('h1');
    if (header) {
      header.style.cssText = `
        background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        background-clip: text;
        display: inline-block;
        padding: 0.5rem 0;
        border-bottom: 3px solid #667eea;
      `;
      
      // Adiciona contador de hosts
      const hostCount = document.querySelectorAll('.host-card').length;
      const counter = document.createElement('span');
      counter.textContent = ` (${hostCount} hosts)`;
      counter.style.cssText = `
        font-size: 1rem;
        color: #6B7280;
        margin-left: 0.5rem;
        -webkit-text-fill-color: #6B7280;
      `;
      header.appendChild(counter);
    }
  },

  // Adiciona estatísticas do grupo
  addGroupStats() {
    const statsDiv = document.createElement('div');
    statsDiv.id = 'groupStats';
    statsDiv.style.cssText = `
      display: flex;
      gap: 1rem;
      margin-bottom: 1rem;
      padding: 0.75rem;
      background: #F9FAFB;
      border-radius: 0.5rem;
      font-size: 0.875rem;
    `;
    
    const container = document.querySelector('h1')?.parentNode;
    if (container && !document.getElementById('groupStats')) {
      container.insertBefore(statsDiv, document.getElementById('hostsContainer'));
    }
    
    return statsDiv;
  },

  // Atualiza estatísticas do grupo
  updateGroupStats(stats) {
    const statsDiv = document.getElementById('groupStats');
    if (!statsDiv) return;
    
    statsDiv.innerHTML = `
      <div style="display: flex; align-items: center; gap: 0.5rem;">
        <span style="color: #10B981;">🟢</span>
        <span>UP: ${stats.up || 0}</span>
      </div>
      <div style="display: flex; align-items: center; gap: 0.5rem;">
        <span style="color: #EF4444;">🔴</span>
        <span>DOWN: ${stats.down || 0}</span>
      </div>
      <div style="display: flex; align-items: center; gap: 0.5rem;">
        <span style="color: #6B7280;">⚪</span>
        <span>Unknown: ${stats.unknown || 0}</span>
      </div>
      <div style="margin-left: auto; font-weight: 600;">
        Total: ${stats.total || 0}
      </div>
    `;
  }
};

// Inicializa estilização quando DOM estiver pronto
document.addEventListener('DOMContentLoaded', () => {
  HostStyler.applyBaseStyles();
  HostStyler.addIcons();
  GroupStyler.setupGrid();
  
  // Adiciona atributo data-hostid aos cards
  document.querySelectorAll('.host-card').forEach(card => {
    const onclick = card.getAttribute('onclick');
    const match = onclick?.match(/openHostModal\((\d+)\)/);
    if (match) {
      card.setAttribute('data-hostid', match[1]);
    }
  });
  
  // Estiliza cabeçalho se houver grupo
  if (typeof grupo !== 'undefined') {
    GroupStyler.styleHeader(grupo);
    GroupStyler.addGroupStats();
  }
});

// Exporta para uso global
window.HostStyler = HostStyler;
window.GroupStyler = GroupStyler;