// static/js/metrics.js

async function atualizarHost(hostid) {
  try {
    const res = await fetch(`/api/host_details/${hostid}`);
    const data = await res.json();

    /* ======================
       STATUS (COM ANIMAÇÃO)
    ====================== */
    const statusEl = document.getElementById(`status-${hostid}`);
    if (statusEl) {
      let color = "text-gray-400";
      let dot = "bg-gray-400 animate-pulse";
      let label = data.status || "UNKNOWN";

      if (data.status === "UP") {
        color = "text-green-600";
        dot = "bg-green-500 animate-ping";
      } else if (data.status === "DOWN") {
        color = "text-red-600";
        dot = "bg-red-600 animate-bounce";
      }

      statusEl.innerHTML = `
        <span class="w-2 h-2 rounded-full ${dot}"></span>
        ${label}
      `;

      statusEl.className =
        `text-sm font-semibold mt-1 flex items-center gap-2 ${color}`;
    }

    /* ======================
       OS
    ====================== */
    const osEl = document.getElementById(`os-${hostid}`);
    if (osEl && data.os) {
      osEl.innerText = data.os.toUpperCase();
    }

    /* ======================
       MÉTRICAS
    ====================== */
    const metricsEl = document.getElementById(`host-metrics-${hostid}`);
    if (metricsEl) {
      const pingTxt = formatPing(data.icmp_ping);
      const latencyTxt = formatLatency(data.latency_ms);
      const uptimeTxt = formatUptime(data.uptime_seconds);

      metricsEl.innerText =
        `Ping: ${pingTxt} • Latência: ${latencyTxt} • Uptime: ${uptimeTxt}`;
    }

    /* ======================
       CPU
    ====================== */
    const cpuBar = document.getElementById(`cpu-${hostid}`);
    const cpuVal = document.getElementById(`cpu-val-${hostid}`);

    if (cpuBar && cpuVal) {
      let cpuPercent = null;

      if (typeof data.cpu === "number") {
        cpuPercent = data.cpu;
      }

      if (typeof data.cpu === "object" && data.cpu !== null) {
        if (typeof data.cpu.used === "number") {
          cpuPercent = data.cpu.used;
        }
      }

      if (cpuPercent !== null) {
        cpuBar.style.width = `${cpuPercent}%`;
        cpuVal.innerText = `${cpuPercent.toFixed(2)}%`;
      } else {
        cpuBar.style.width = "0%";
        cpuVal.innerText = "N/A";
      }
    }

    /* ======================
       MEMÓRIA
    ====================== */
    const memBar = document.getElementById(`mem-${hostid}`);
    const memVal = document.getElementById(`mem-val-${hostid}`);

    if (data.memoria && memBar && memVal) {
      memBar.style.width = `${data.memoria.percent}%`;
      memVal.innerText =
        `${data.memoria.used_gb} / ${data.memoria.total_gb} GB (${data.memoria.percent}%)`;
    } else if (memVal) {
      memVal.innerText = "N/A";
    }

    /* ======================
       DISK
    ====================== */
    const disksDiv = document.getElementById(`disks-${hostid}`);
    if (disksDiv) {
      disksDiv.innerHTML = "";

      if (data.discos && data.discos.length > 0) {
        data.discos.forEach(d => {
          disksDiv.innerHTML += `
            <div>
              <div class="flex justify-between mb-1">
                <span class="font-medium">${d.mount}</span>
                <span class="font-semibold">${d.uso}%</span>
              </div>
              <div class="w-full bg-gray-200 rounded h-6 relative">
                <div class="bg-yellow-500 h-6 rounded transition-all duration-700"
                     style="width:${d.uso}%"></div>
                <span class="absolute left-1/2 top-1/2 
                             -translate-x-1/2 -translate-y-1/2 
                             text-xs font-semibold text-gray-800">
                  ${d.uso}%
                </span>
              </div>
            </div>
          `;
        });
      } else {
        disksDiv.innerHTML =
          "<span class='text-gray-400'>Sem discos</span>";
      }
    }

  } catch (err) {
    console.error(`Erro host ${hostid}:`, err);
  }
}

/* ======================
   INICIALIZAÇÃO
====================== */
document.addEventListener("DOMContentLoaded", () => {
  if (typeof HOSTS === "undefined") return;

  HOSTS.forEach(h => {
    atualizarHost(h.hostid);
    setInterval(() => atualizarHost(h.hostid), 5000);
  });

  /* ======================
     BUSCA
  ====================== */
  const searchBox = document.getElementById('searchBox');
  const hostCards = document.querySelectorAll('.host-card');

  if (searchBox) {
    searchBox.addEventListener('input', function () {
      const searchTerm = this.value.toLowerCase().trim();

      hostCards.forEach(card => {
        const hostname = card.dataset.hostname.toLowerCase();
        card.style.display =
          hostname.includes(searchTerm) ? 'block' : 'none';
      });
    });
  }
});

/* ======================
   HELPERS
====================== */
function formatPing(value) {
  if (value === null || value === undefined) return "N/A";
  return value === 1 ? "OK" : "Sem resposta";
}

function formatLatency(ms) {
  if (ms === null || ms === undefined) return "N/A";
  return `${ms.toFixed(2)} ms`;
}

function formatUptime(seconds) {
  if (!seconds || seconds <= 0) return "N/A";

  const d = Math.floor(seconds / 86400);
  const h = Math.floor((seconds % 86400) / 3600);
  const m = Math.floor((seconds % 3600) / 60);

  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}