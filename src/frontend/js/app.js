document.addEventListener("DOMContentLoaded", () => {
    
    // Variables
    const navItems = document.querySelectorAll(".nav-item");
    const views = document.querySelectorAll(".view-container");
    const btnProcess = document.getElementById("btn-process");
    const startAccountScope = document.getElementById("start-account-scope");

    const appContainer = document.querySelector(".app-container");
    const sidebarToggle = document.getElementById("btn-toggle-sidebar");
    if(sidebarToggle && appContainer) {
        const collapsed = localStorage.getItem("oculus-sidebar-collapsed") === "1";
        appContainer.classList.toggle("sidebar-collapsed", collapsed);
        sidebarToggle.addEventListener("click", () => {
            const isCollapsed = appContainer.classList.toggle("sidebar-collapsed");
            localStorage.setItem("oculus-sidebar-collapsed", isCollapsed ? "1" : "0");
            sidebarToggle.innerHTML = `<i class="fa-solid fa-chevron-${isCollapsed ? "right" : "left"}"></i>`;
            sidebarToggle.title = isCollapsed ? "Mostrar menú lateral" : "Ocultar menú lateral";
        });
        if(collapsed) {
            sidebarToggle.innerHTML = '<i class="fa-solid fa-chevron-right"></i>';
            sidebarToggle.title = "Mostrar menú lateral";
        }
    }
    
    // Elements for stats
    const statProcessed = document.getElementById("stat-processed");
    const statPending = document.getElementById("stat-pending");
    const statOthers = document.getElementById("stat-others");
    const statErrors = document.getElementById("stat-errors");

    // Initialize pywebview integration
    // We listen to the pywebviewready event which is fired when window.pywebview is available
    window.addEventListener('pywebviewready', function() {
        showToast("Conectado al motor Python de Oculus.");
        loadStartAccountOptions();
        updateTelemetry();
    });

    // Navigation logic
    navItems.forEach(item => {
        item.addEventListener("click", (e) => {
            e.preventDefault();
            
            // Remove active from all
            navItems.forEach(nav => nav.classList.remove("active"));
            views.forEach(view => view.classList.remove("active"));
            
            // Add active to clicked
            item.classList.add("active");
            const targetView = item.getAttribute("data-view");
            const viewElement = document.getElementById(`view-${targetView}`);
            
            if(viewElement) {
                viewElement.classList.add("active");
                document.getElementById("view-title").textContent = item.querySelector("span").textContent;
                
                // Si es la vista de DTEs, cargar clientes
                if(targetView === "dtes") {
                    loadClients();
                } else if(targetView === "emails") {
                    loadCompanies();
                    loadEmails();
                } else if(targetView === "review") {
                    loadReviews();
                } else if(targetView === "explorer") {
                    loadExplorer();
                } else if(targetView === "settings") {
                    loadSettings();
                } else if(targetView === "recovery") {
                    loadRecoveryAccounts();
                    loadRecoveryBackups();
                }
            } else {
                showToast(`Vista ${targetView} en desarrollo.`);
                document.getElementById("view-dashboard").classList.add("active");
            }
        });
    });

    // Process button
    btnProcess.addEventListener("click", async () => {
        btnProcess.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Procesando...';
        btnProcess.disabled = true;
        
        try {
            if(window.pywebview && window.pywebview.api) {
                const result = await window.pywebview.api.start_processing(startAccountScope ? startAccountScope.value : "");
                showToast(result);
            } else {
                showToast("Error: API no disponible.");
                btnProcess.innerHTML = '<i class="fa-solid fa-play"></i> Iniciar Monitoreo';
                btnProcess.disabled = false;
            }
        } catch (error) {
            showToast("Ocurrió un error.");
            btnProcess.innerHTML = '<i class="fa-solid fa-play"></i> Iniciar Monitoreo';
            btnProcess.disabled = false;
        }
    });

    async function loadStartAccountOptions() {
        if(!startAccountScope || !window.pywebview || !window.pywebview.api) return;
        const accounts = await window.pywebview.api.get_emails();
        accounts.forEach(account => {
            const option = document.createElement("option");
            option.value = account.email;
            option.textContent = `${account.client || "Sin empresa"} - ${account.email}`;
            startAccountScope.appendChild(option);
        });
    }

    // DTE Generator logic
    const selClient = document.getElementById("sel-client");
    const selMonth = document.getElementById("sel-month");
    const inputPath = document.getElementById("input-path");
    const btnGenerateExcel = document.getElementById("btn-generate-excel");
    const excelDiagnostics = document.getElementById("excel-diagnostics");

    async function loadClients() {
        if(window.pywebview && window.pywebview.api) {
            const toggle = document.getElementById("toggle-show-recovery");
            const includeRecovery = toggle ? toggle.checked : false;
            const clients = await window.pywebview.api.get_clients(includeRecovery);
            selClient.innerHTML = '<option value="">-- Seleccione un cliente --</option>';
            clients.forEach(c => {
                selClient.innerHTML += `<option value="${c}">${c}</option>`;
            });
            if(excelDiagnostics) {
                excelDiagnostics.textContent = clients.length
                    ? `Clientes encontrados: ${clients.length}. Seleccione un cliente para ver sus períodos.`
                    : "No hay carpetas de clientes en la ruta de datos procesados.";
            }
        }
    }

    async function refreshExcelDiagnostics() {
        if(!excelDiagnostics || !window.pywebview || !window.pywebview.api || !window.pywebview.api.get_excel_diagnostics) return;
        const diagnostics = await window.pywebview.api.get_excel_diagnostics(selClient.value, selMonth.value);
        const periods = diagnostics.periods.length ? diagnostics.periods.join(", ") : "ninguno";
        const selected = diagnostics.selected_path || diagnostics.client_path || diagnostics.processed_dir;
        excelDiagnostics.textContent = `Ruta activa: ${selected} | Períodos: ${periods} | JSON del período: ${diagnostics.json_count} | Base: ${diagnostics.database} (${diagnostics.database_exists ? "creada" : "no encontrada"})`;
    }

    const toggleShowRecovery = document.getElementById("toggle-show-recovery");
    if(toggleShowRecovery) {
        toggleShowRecovery.addEventListener("change", () => {
            selClient.value = "";
            selMonth.innerHTML = '<option value="">-- Seleccione un cliente primero --</option>';
            selMonth.disabled = true;
            loadClients();
        });
    }

    selClient.addEventListener("change", async (e) => {
        const client = e.target.value;
        if(client && window.pywebview && window.pywebview.api) {
            const months = await window.pywebview.api.get_months(client);
            selMonth.innerHTML = '<option value="">-- Seleccione un mes --</option>';
            months.forEach(m => {
                selMonth.innerHTML += `<option value="${m}">${m}</option>`;
            });
            selMonth.disabled = false;
        } else {
            selMonth.innerHTML = '<option value="">-- Seleccione un cliente primero --</option>';
            selMonth.disabled = true;
        }
        await refreshExcelDiagnostics();
        checkFormReady();
    });

    selMonth.addEventListener("change", async () => {
        await refreshExcelDiagnostics();
        checkFormReady();
    });

    inputPath.addEventListener("click", async () => {
        if(window.pywebview && window.pywebview.api) {
            const dir = await window.pywebview.api.choose_directory();
            if(dir) {
                inputPath.value = dir;
                checkFormReady();
            }
        }
    });

    function checkFormReady() {
        if(selClient.value && selMonth.value && inputPath.value) {
            btnGenerateExcel.disabled = false;
        } else {
            btnGenerateExcel.disabled = true;
        }
    }

    btnGenerateExcel.addEventListener("click", async () => {
        btnGenerateExcel.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Generando...';
        btnGenerateExcel.disabled = true;
        const btnOpenExport = document.getElementById("btn-open-export");
        if(btnOpenExport) btnOpenExport.style.display = "none";
        try {
            const result = await window.pywebview.api.generate_excel(
                selClient.value, selMonth.value, inputPath.value
            );
            // generate_excel devuelve (success, mensaje, ruta_carpeta).
            const success = result[0];
            const message = result[1];
            const exportPath = result.length > 2 ? result[2] : null;
            showToast(message);
            if(success && exportPath && btnOpenExport) {
                btnOpenExport.style.display = "";
                btnOpenExport.onclick = async () => {
                    try {
                        const opened = await window.pywebview.api.open_folder(exportPath);
                        showToast(opened[1]);
                    } catch(e) {
                        showToast("No se pudo abrir la carpeta.");
                    }
                };
            }
            if(!success && window.pywebview.api.get_excel_diagnostics) {
                const diagnostics = await window.pywebview.api.get_excel_diagnostics(
                    selClient.value, selMonth.value
                );
                excelDiagnostics.textContent = `Ruta activa: ${diagnostics.selected_path || diagnostics.client_path || diagnostics.processed_dir} | Períodos disponibles: ${diagnostics.periods.join(", ") || "ninguno"} | JSON encontrados: ${diagnostics.json_count} | Base: ${diagnostics.database} (${diagnostics.database_exists ? "creada" : "no encontrada"})`;
            }
        } catch (error) {
            showToast("Error al generar el Excel.");
            if(excelDiagnostics) excelDiagnostics.textContent = `Error técnico: ${error}`;
        }
        btnGenerateExcel.innerHTML = '<i class="fa-solid fa-file-excel"></i> Generar Excel';
        btnGenerateExcel.disabled = false;
    });

    // --- TELEMETRY & LIVE DASHBOARD ---
    let telemetryInterval = null;
    let lastProcessedCount = 0;
    let maxThroughput = 0;
    
    // Chart setup
    const canvas = document.getElementById("live-chart");
    const ctx = canvas ? canvas.getContext("2d") : null;
    const chartData = new Array(60).fill(0);
    
    function drawChart() {
        if (!ctx || !canvas) return;
        const width = canvas.offsetWidth;
        const height = canvas.offsetHeight;
        canvas.width = width;
        canvas.height = height;
        
        ctx.clearRect(0, 0, width, height);
        
        // Find max
        let maxVal = Math.max(...chartData, 10);
        
        ctx.beginPath();
        ctx.moveTo(0, height);
        
        for(let i=0; i<chartData.length; i++) {
            let x = (i / (chartData.length - 1)) * width;
            let y = height - ((chartData[i] / maxVal) * (height - 20)); // padding top
            ctx.lineTo(x, y);
        }
        
        // Fill area
        ctx.lineTo(width, height);
        ctx.closePath();
        let gradient = ctx.createLinearGradient(0, 0, 0, height);
        gradient.addColorStop(0, 'rgba(37, 99, 235, 0.3)');
        gradient.addColorStop(1, 'rgba(37, 99, 235, 0.0)');
        ctx.fillStyle = gradient;
        ctx.fill();
        
        // Stroke line
        ctx.beginPath();
        for(let i=0; i<chartData.length; i++) {
            let x = (i / (chartData.length - 1)) * width;
            let y = height - ((chartData[i] / maxVal) * (height - 20));
            if(i === 0) ctx.moveTo(x, y);
            else ctx.lineTo(x, y);
        }
        ctx.strokeStyle = '#3b82f6';
        ctx.lineWidth = 2;
        ctx.stroke();
        
        requestAnimationFrame(drawChart);
    }
    
    if (canvas) requestAnimationFrame(drawChart);

    function generateMockLog(stage, isError=false) {
        const tbody = document.getElementById("terminal-body");
        if(!tbody) return;
        
        const now = new Date();
        const timeStr = now.toISOString().split('T')[1].substring(0, 12);
        const hexId = Math.floor(Math.random()*65535).toString(16).toUpperCase().padStart(4, '0');
        
        let statusBadge = '';
        if (isError) statusBadge = '<span class="badge-status badge-error">⚠ ERROR</span>';
        else if (stage === "Download") statusBadge = '<span class="badge-status badge-download">⬇ DOWNLOAD</span>';
        else if (stage === "Process") statusBadge = '<span class="badge-status badge-parsed">● PARSED</span>';
        else statusBadge = '<span class="badge-status badge-committed">✓ COMMITTED</span>';
        
        const tr = document.createElement("tr");
        tr.innerHTML = `
            <td>${timeStr}</td>
            <td>0x${hexId}</td>
            <td>${stage}</td>
            <td>${statusBadge}</td>
        `;
        
        // Remove empty state
        const empty = tbody.querySelector(".empty-row");
        if(empty) empty.remove();
        
        tbody.prepend(tr);
        if(tbody.children.length > 50) {
            tbody.lastChild.remove();
        }
    }

    async function updateTelemetry() {
        if(!window.pywebview || !window.pywebview.api) return;
        try {
            const tel = await window.pywebview.api.get_telemetry();
            
            // Update Top KPIs
            const processedEl = document.getElementById("kpi-processed");
            const statusEl = document.getElementById("kpi-status");
            const uptimeEl = document.getElementById("kpi-uptime");
            const errorsEl = document.getElementById("kpi-errors");
            
            if(processedEl) processedEl.textContent = tel.docs_processed;
            if(errorsEl) errorsEl.textContent = tel.errors;
            if(uptimeEl) uptimeEl.textContent = "Uptime: " + Math.floor(tel.uptime_seconds) + "s";

            const processActive = tel.status !== "IDLE";
            btnProcess.disabled = processActive;
            if(processActive && tel.status !== "STOPPING") {
                btnProcess.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Monitoreando...';
            } else if(!processActive) {
                btnProcess.innerHTML = '<i class="fa-solid fa-play"></i> Iniciar Monitoreo';
            }
            const stopButton = document.getElementById("btn-stop-process");
            const closeButton = document.getElementById("btn-close-app");
            if(stopButton) stopButton.disabled = !processActive || tel.status === "STOPPING";
            if(closeButton) closeButton.disabled = processActive;
            
            if(statusEl) {
                statusEl.textContent = tel.status;
                statusEl.className = "kpi-value status-badge";
                if(tel.status === "DOWNLOADING") statusEl.classList.add("status-download");
                else if(tel.status === "PROCESSING") statusEl.classList.add("status-active");
            }
            
            // Calculate simulated docs/s based on state change
            let currentRate = 0;
            if(tel.status === "PROCESSING" || tel.status === "DOWNLOADING") {
                // If it's active, simulate high-frequency flow
                currentRate = Math.floor(Math.random() * 15) + 5; 
                
                // Add mock logs
                if(tel.status === "DOWNLOADING") generateMockLog("Download");
                else {
                    generateMockLog("Process");
                    setTimeout(() => generateMockLog("Storage"), 200);
                }
            } else if (tel.status === "STARTING") {
                generateMockLog("System", false);
            }
            
            // Chart Data shift
            chartData.push(currentRate);
            chartData.shift();
            
            const throughputEl = document.getElementById("kpi-throughput");
            if(throughputEl) throughputEl.textContent = currentRate.toFixed(1);
            
            if(currentRate > maxThroughput) {
                maxThroughput = currentRate;
                const maxEl = document.getElementById("kpi-throughput-max");
                if(maxEl) maxEl.textContent = maxThroughput.toFixed(1);
            }
            
            // Update pipeline nodes
            document.getElementById("node-download")?.classList.toggle("active", tel.status === "DOWNLOADING");
            document.getElementById("node-process")?.classList.toggle("active", tel.status === "PROCESSING");
            document.getElementById("node-db")?.classList.toggle("active", tel.status === "PROCESSING");
            document.getElementById("conn-1")?.classList.toggle("active", tel.status === "DOWNLOADING" || tel.status === "PROCESSING");
            document.getElementById("conn-2")?.classList.toggle("active", tel.status === "PROCESSING");
            
        } catch(e) {}
    }
    
    // Start telemetry loop
    telemetryInterval = setInterval(updateTelemetry, 1000);

    function showToast(message) {
        const toast = document.getElementById("toast");
        const toastMsg = document.getElementById("toast-msg");
        toastMsg.textContent = message;
        toast.classList.add("show");
        setTimeout(() => toast.classList.remove("show"), 3000);
    }
    // --- GLOBAL CONTROLS ---
    const btnStopProcess = document.getElementById("btn-stop-process");
    const btnCloseApp = document.getElementById("btn-close-app");

    const recoveryAccount = document.getElementById("recovery-account");
    const recoveryStatus = document.getElementById("recovery-status");
    const btnStartRecovery = document.getElementById("btn-start-recovery");
    const btnStopRecovery = document.getElementById("btn-stop-recovery");

    async function loadRecoveryAccounts() {
        if(!recoveryAccount || !window.pywebview || !window.pywebview.api) return;
        const accounts = await window.pywebview.api.get_emails();
        recoveryAccount.innerHTML = '<option value="">-- Seleccione una cuenta --</option>';
        accounts.forEach(account => {
            const option = document.createElement("option");
            option.value = account.email;
            option.textContent = `${account.client || "Sin empresa"} - ${account.email}`;
            recoveryAccount.appendChild(option);
        });
    }

    function formatBytes(total) {
        if(!total) return "0 B";
        const units = ["B", "KB", "MB", "GB"];
        let value = total;
        let unit = 0;
        while(value >= 1024 && unit < units.length - 1) { value /= 1024; unit++; }
        return `${value.toFixed(1)} ${units[unit]}`;
    }

    async function loadRecoveryBackups() {
        const listContainer = document.getElementById("recovery-backups-list");
        if(!listContainer || !window.pywebview || !window.pywebview.api || !window.pywebview.api.get_recovery_backups) return;
        listContainer.innerHTML = '<div class="empty-state"><i class="fa-solid fa-spinner fa-spin"></i><p>Cargando respaldos...</p></div>';
        try {
            const backups = await window.pywebview.api.get_recovery_backups();
            if(!backups || backups.length === 0) {
                listContainer.innerHTML = '<div class="empty-state"><i class="fa-solid fa-box-open"></i><p>No hay respaldos de recuperación.</p></div>';
                return;
            }
            listContainer.innerHTML = '<ul class="activity-list"></ul>';
            const ul = listContainer.querySelector("ul");
            backups.forEach(backup => {
                const dateStr = backup.updated ? new Date(backup.updated * 1000).toLocaleString() : "sin fecha";
                const li = document.createElement("li");
                li.className = "activity-item";
                li.style.justifyContent = "space-between";
                li.innerHTML = `
                    <div style="display:flex; gap:12px; align-items:center;">
                        <i class="fa-solid fa-box-archive" style="color: var(--warning);"></i>
                        <div>
                            <strong style="display:block;">${backup.alias}</strong>
                            <small class="text-muted">${backup.files} archivos · ${formatBytes(backup.size_bytes)} · ${dateStr}</small>
                        </div>
                    </div>
                    <button class="icon-btn btn-delete-backup" data-alias="${backup.alias}" title="Eliminar respaldo" aria-label="Eliminar respaldo ${backup.alias}" style="color: var(--danger);"><i class="fa-solid fa-trash"></i></button>`;
                ul.appendChild(li);
            });
            listContainer.querySelectorAll(".btn-delete-backup").forEach(btn => {
                btn.addEventListener("click", async () => {
                    const alias = btn.getAttribute("data-alias");
                    if(confirm(`Se eliminarán los archivos del respaldo '${alias}'. Esta acción no se puede deshacer. ¿Continuar?`)) {
                        try {
                            const res = await window.pywebview.api.delete_client_data(alias, true, false);
                            showToast(res[1]);
                            if(res[0]) { loadRecoveryBackups(); }
                        } catch(e) {
                            showToast("Error al eliminar el respaldo.");
                        }
                    }
                });
            });
        } catch(e) {
            listContainer.innerHTML = '<div class="empty-state"><p>Error al cargar respaldos.</p></div>';
        }
    }

    const btnRefreshBackups = document.getElementById("btn-refresh-backups");
    if(btnRefreshBackups) btnRefreshBackups.addEventListener("click", loadRecoveryBackups);

    if(btnStartRecovery) btnStartRecovery.addEventListener("click", async () => {
        const autoCleanupEl = document.getElementById("recovery-auto-cleanup");
        const result = await window.pywebview.api.start_recovery(
            recoveryAccount.value,
            document.getElementById("recovery-alias").value,
            document.getElementById("recovery-start-date").value,
            document.getElementById("recovery-end-date").value,
            autoCleanupEl ? autoCleanupEl.checked : false
        );
        showToast(result[1]);
        if(result[0]) {
            btnStartRecovery.disabled = true;
            btnStopRecovery.disabled = false;
        }
    });

    if(btnStopRecovery) btnStopRecovery.addEventListener("click", async () => {
        const result = await window.pywebview.api.stop_recovery();
        showToast(result[1]);
        btnStopRecovery.disabled = true;
    });

    setInterval(async () => {
        if(!recoveryStatus || !window.pywebview || !window.pywebview.api || !window.pywebview.api.get_recovery_status) return;
        const status = await window.pywebview.api.get_recovery_status();
        if(status.status !== "IDLE") recoveryStatus.textContent = status.message;
        if(status.status === "IDLE" && btnStartRecovery) {
            recoveryStatus.textContent = status.message;
            btnStartRecovery.disabled = false;
            if(btnStopRecovery) btnStopRecovery.disabled = true;
        }
    }, 2000);

    btnStopProcess.addEventListener("click", async () => {
        if(window.pywebview && window.pywebview.api) {
            btnStopProcess.disabled = true;
            btnStopProcess.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Terminando...';
            const result = await window.pywebview.api.stop_processing();
            showToast(result[1]);
            btnStopProcess.innerHTML = '<i class="fa-solid fa-stop"></i> Detener proceso';
        }
    });

    btnCloseApp.addEventListener("click", async () => {
        if(window.pywebview && window.pywebview.api) {
            const result = await window.pywebview.api.shutdown_service();
            if(!result[0]) showToast(result[1]);
        }
    });

    // --- EMAIL MANAGEMENT ---
    const btnAddEmail = document.getElementById("btn-add-email");
    const btnRefreshEmails = document.getElementById("btn-refresh-emails");
    const emailsList = document.getElementById("emails-list-container");
    const clientSelect = document.getElementById("email-client-name");
    const btnAddCompany = document.getElementById("btn-add-company");
    const companyForm = document.getElementById("company-form");
    const newCompanyAlias = document.getElementById("new-company-alias");
    const btnSaveCompany = document.getElementById("btn-save-company");

    document.getElementById("email-provider").addEventListener("change", (e) => {
        document.getElementById("custom-imap-group").style.display = e.target.value === "custom" ? "block" : "none";
    });

    async function loadCompanies() {
        if(!clientSelect || !window.pywebview || !window.pywebview.api || !window.pywebview.api.get_companies) return;
        const companies = await window.pywebview.api.get_companies();
        const selected = clientSelect.value;
        clientSelect.innerHTML = '<option value="">-- Seleccione una empresa --</option>';
        companies.forEach(company => {
            const option = document.createElement("option");
            option.value = company.alias;
            option.textContent = company.alias;
            clientSelect.appendChild(option);
        });
        if(selected) clientSelect.value = selected;
    }

    if(btnAddCompany) {
        btnAddCompany.addEventListener("click", () => {
            if(companyForm) companyForm.style.display = companyForm.style.display === "none" ? "block" : "none";
            if(newCompanyAlias) newCompanyAlias.focus();
        });
    }

    if(btnSaveCompany) {
        btnSaveCompany.addEventListener("click", async () => {
            const alias = newCompanyAlias ? newCompanyAlias.value.trim() : "";
            if(!alias || !window.pywebview || !window.pywebview.api) return;
            const result = await window.pywebview.api.add_company(alias);
            showToast(result[1]);
            if(result[0]) {
                await loadCompanies();
                clientSelect.value = alias;
                newCompanyAlias.value = "";
                if(companyForm) companyForm.style.display = "none";
            }
        });
    }

    async function loadEmails() {
        if(!window.pywebview || !window.pywebview.api) return;
        
        emailsList.innerHTML = '<div class="empty-state"><i class="fa-solid fa-spinner fa-spin"></i><p>Cargando...</p></div>';
        
        try {
            const emails = await window.pywebview.api.get_emails();
            if(emails && emails.length > 0) {
                const groups = {};
                emails.forEach(em => {
                    const alias = em.client || 'Sin empresa';
                    if(!groups[alias]) groups[alias] = [];
                    groups[alias].push(em);
                });
                emailsList.innerHTML = '<div class="company-groups"></div>';
                const groupsContainer = emailsList.querySelector(".company-groups");
                Object.entries(groups).forEach(([alias, accounts]) => {
                    const group = document.createElement("details");
                    group.className = "company-group";
                    group.open = true;
                    group.innerHTML = `<summary><i class="fa-solid fa-folder-open"></i><strong>${alias}</strong><span class="badge badge-teal">${accounts.length} cuenta${accounts.length === 1 ? '' : 's'}</span></summary><ul class="activity-list"></ul>`;
                    const ul = group.querySelector("ul");
                    accounts.forEach(em => ul.innerHTML += `
                        <li class="activity-item" style="justify-content: space-between;">
                            <div style="display: flex; gap: 12px; align-items: center;">
                                <i class="fa-solid fa-envelope teal-text"></i>
                                <div>
                                    <strong style="display:block;">${em.email}</strong>
                                    <small class="text-muted">${em.client || 'Sin cliente'} - ${em.server}</small>
                                </div>
                            </div>
                            <div style="display: flex; gap: 10px; align-items: center;">
                                <span class="badge ${em.active ? 'badge-teal' : 'bg-danger'}">${em.active ? 'Activo' : 'Error'}</span>
                                <button class="icon-btn btn-edit-account" data-email="${em.email}" title="Editar Cuenta"><i class="fa-solid fa-pen"></i></button>
                                <button class="icon-btn btn-delete-account" data-email="${em.email}" title="Eliminar Cuenta" style="color: var(--danger);"><i class="fa-solid fa-trash"></i></button>
                            </div>
                        </li>
                    `);
                    groupsContainer.appendChild(group);
                });
                
                // Add event listeners for edit and delete
                document.querySelectorAll(".btn-edit-account").forEach(btn => {
                    btn.addEventListener("click", () => {
                        const email = btn.getAttribute("data-email");
                        const account = emails.find(e => e.email === email);
                        if(account) {
                            document.getElementById("form-account-title").innerHTML = '<i class="fa-solid fa-pen teal-text"></i> Editar Cuenta';
                            document.getElementById("btn-cancel-edit").style.display = 'block';
                            document.getElementById("email-old-address").value = account.email;
                            document.getElementById("email-client-name").value = account.client || '';
                            document.getElementById("email-address").value = account.email;
                            document.getElementById("email-port").value = account.port;
                            document.getElementById("email-start-date").value = account.start_date || "2026-05-01";
                            
                            // Try to match provider
                            const providerEl = document.getElementById("email-provider");
                            const customInput = document.getElementById("custom-imap-server");
                            const customGroup = document.getElementById("custom-imap-group");
                            
                            if(account.server === "imap.gmail.com" || account.server === "outlook.office365.com") {
                                providerEl.value = account.server;
                                customGroup.style.display = "none";
                            } else {
                                providerEl.value = "custom";
                                customGroup.style.display = "block";
                                customInput.value = account.server;
                            }
                            
                            document.getElementById("email-password").value = account.password_encrypted || '';
                        }
                    });
                });
                
                document.querySelectorAll(".btn-delete-account").forEach(btn => {
                    btn.addEventListener("click", async () => {
                        const email = btn.getAttribute("data-email");
                        if(confirm(`¿Estás seguro de que quieres eliminar la cuenta ${email}?`)) {
                            try {
                                const res = await window.pywebview.api.delete_email(email);
                                showToast(res[1]);
                                loadEmails();
                            } catch(e) {
                                showToast("Error al eliminar la cuenta");
                            }
                        }
                    });
                });
                
            } else {
                emailsList.innerHTML = `
                    <div class="empty-state">
                        <i class="fa-solid fa-inbox"></i>
                        <p>No hay cuentas configuradas.</p>
                        <small>Usa el formulario de la izquierda para agregar la primera.</small>
                    </div>`;
            }
        } catch(e) {
            emailsList.innerHTML = '<div class="empty-state"><p>Error cargando correos.</p></div>';
        }
    }

    btnRefreshEmails.addEventListener("click", loadEmails);

    btnAddEmail.addEventListener("click", async () => {
        const oldEmail = document.getElementById("email-old-address").value;
        const client = document.getElementById("email-client-name").value;
        const email = document.getElementById("email-address").value;
        let provider = document.getElementById("email-provider").value;
        if(provider === "custom") provider = document.getElementById("custom-imap-server").value;
        const pass = document.getElementById("email-password").value;
        const portVal = document.getElementById("email-port") ? document.getElementById("email-port").value : "993";
        const port = parseInt(portVal, 10) || 993;
        const startDate = document.getElementById("email-start-date").value || "2026-05-01";

        if(!client || !email || !provider || !pass) {
            showToast("Seleccione una empresa y complete los campos obligatorios.");
            return;
        }

        btnAddEmail.disabled = true;
        btnAddEmail.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Registrando...';

        try {
            let res;
            if(oldEmail) {
                res = await window.pywebview.api.update_email(oldEmail, client, email, pass, provider, port, startDate);
            } else {
                res = await window.pywebview.api.add_email(client, email, pass, provider, port, startDate);
            }
            showToast(res[1]);
            if(res[0]) {
                document.getElementById("btn-cancel-edit").click(); // Reset form
                loadEmails();
            }
        } catch(e) {
            showToast("Error de conexión con Python.");
        }

        btnAddEmail.disabled = false;
        btnAddEmail.innerHTML = '<i class="fa-solid fa-user-plus"></i> Guardar Cuenta';
    });

    document.getElementById("btn-cancel-edit").addEventListener("click", () => {
        document.getElementById("email-old-address").value = '';
        document.getElementById("email-client-name").value = '';
        document.getElementById("email-address").value = '';
        document.getElementById("email-password").value = '';
        document.getElementById("form-account-title").innerHTML = '<i class="fa-solid fa-circle-plus teal-text"></i> Agregar Nueva Cuenta';
        document.getElementById("btn-cancel-edit").style.display = 'none';
        document.getElementById("email-provider").value = "imap.gmail.com";
        document.getElementById("custom-imap-group").style.display = "none";
        document.getElementById("email-port").value = "993";
        document.getElementById("email-start-date").value = "2026-05-01";
    });

    // --- MANUAL REVIEW STATION ---
    let pendingReviews = [];
    let currentReviewIndex = 0;
    const btnPrevReview = document.getElementById("btn-prev-review");
    const btnNextReview = document.getElementById("btn-next-review");
    const btnSaveReview = document.getElementById("btn-save-review");
    const reviewCounter = document.getElementById("review-counter");
    const pdfEmbed = document.getElementById("pdf-embed");
    const emptyStateReview = document.getElementById("review-empty-state");

    async function loadReviews() {
        if(!window.pywebview || !window.pywebview.api) return;
        try {
            pendingReviews = await window.pywebview.api.get_manual_reviews();
            if(pendingReviews.length > 0) {
                currentReviewIndex = 0;
                emptyStateReview.style.display = 'none';
                pdfEmbed.style.display = 'block';
                updateReviewUI();
            } else {
                emptyStateReview.style.display = 'flex';
                pdfEmbed.style.display = 'none';
                reviewCounter.textContent = '0 / 0';
                btnSaveReview.disabled = true;
                btnPrevReview.disabled = true;
                btnNextReview.disabled = true;
            }
        } catch(e) {
            console.error(e);
        }
    }

    function updateReviewUI() {
        const doc = pendingReviews[currentReviewIndex];
        reviewCounter.textContent = `${currentReviewIndex + 1} / ${pendingReviews.length}`;
        
        // Navigation buttons
        btnPrevReview.disabled = currentReviewIndex === 0;
        btnNextReview.disabled = currentReviewIndex === pendingReviews.length - 1;
        btnSaveReview.disabled = false;

        // Load PDF
        pdfEmbed.src = "file:///" + doc.pdf_path; // Only works if local files are allowed, otherwise needs a python route

        // Populate fields if any were extracted with low confidence
        document.getElementById("rev-uuid").value = doc.uuid || '';
        document.getElementById("rev-sello").value = doc.sello || '';
        document.getElementById("rev-control").value = doc.control || '';
        document.getElementById("rev-date").value = doc.date || '';
        document.getElementById("rev-type").value = doc.type || '03';
        document.getElementById("rev-provider-name").value = doc.provider_name || '';
        document.getElementById("rev-provider-nit").value = doc.provider_nit || '';
        
        // Reset amounts
        document.getElementById("rev-subtotal").value = '';
        document.getElementById("rev-iva").value = '';
        document.getElementById("rev-tax-input").value = '';
        document.getElementById("rev-tax-list").innerHTML = '';
        document.getElementById("rev-taxes-total").value = '0';
        document.getElementById("rev-grand-total").textContent = '0.00';
    }

    // --- Montos e Impuestos Dinámicos ---
    const inputSubtotal = document.getElementById("rev-subtotal");
    const inputIva = document.getElementById("rev-iva");
    const inputTax = document.getElementById("rev-tax-input");
    const btnAddTax = document.getElementById("btn-add-tax");
    const taxList = document.getElementById("rev-tax-list");
    const inputTaxesTotal = document.getElementById("rev-taxes-total");
    const displayGrandTotal = document.getElementById("rev-grand-total");

    function calculateTotals() {
        let subtotal = parseFloat(inputSubtotal.value) || 0;
        let iva = subtotal * 0.13;
        let otherTaxes = parseFloat(inputTaxesTotal.value) || 0;
        
        inputIva.value = iva.toFixed(2);
        let grandTotal = subtotal + iva + otherTaxes;
        displayGrandTotal.textContent = grandTotal.toFixed(2);
    }

    inputSubtotal.addEventListener("input", calculateTotals);

    function addTax() {
        let taxVal = parseFloat(inputTax.value);
        if(!isNaN(taxVal) && taxVal > 0) {
            // Update total
            let currentTotal = parseFloat(inputTaxesTotal.value) || 0;
            currentTotal += taxVal;
            inputTaxesTotal.value = currentTotal;
            
            // Add to UI list
            const li = document.createElement("li");
            li.className = "activity-item";
            li.style.padding = "5px 10px";
            li.innerHTML = `<span>Impuesto:</span> <strong>$${taxVal.toFixed(2)}</strong>`;
            taxList.appendChild(li);
            
            // Reset input and recalc
            inputTax.value = '';
            calculateTotals();
        }
    }

    btnAddTax.addEventListener("click", addTax);
    inputTax.addEventListener("keypress", (e) => {
        if(e.key === 'Enter') {
            e.preventDefault();
            addTax();
        }
    });

    btnPrevReview.addEventListener("click", () => {
        if(currentReviewIndex > 0) {
            currentReviewIndex--;
            updateReviewUI();
        }
    });

    btnNextReview.addEventListener("click", () => {
        if(currentReviewIndex < pendingReviews.length - 1) {
            currentReviewIndex++;
            updateReviewUI();
        }
    });

    btnSaveReview.addEventListener("click", async () => {
        const data = {
            id: pendingReviews[currentReviewIndex].id,
            pdf_path: pendingReviews[currentReviewIndex].pdf_path,
            uuid: document.getElementById("rev-uuid").value,
            sello: document.getElementById("rev-sello").value,
            control: document.getElementById("rev-control").value,
            date: document.getElementById("rev-date").value,
            type: document.getElementById("rev-type").value,
            provider_name: document.getElementById("rev-provider-name").value,
            provider_nit: document.getElementById("rev-provider-nit").value,
            subtotal: parseFloat(document.getElementById("rev-subtotal").value) || 0,
            iva: parseFloat(document.getElementById("rev-iva").value) || 0,
            otros_impuestos: parseFloat(document.getElementById("rev-taxes-total").value) || 0,
            total: parseFloat(document.getElementById("rev-grand-total").textContent) || 0
        };

        btnSaveReview.disabled = true;
        btnSaveReview.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Guardando...';

        try {
            await window.pywebview.api.save_manual_review(data);
            showToast("Datos guardados. DTE procesado.");
            // Remove from list and update
            pendingReviews.splice(currentReviewIndex, 1);
            if(currentReviewIndex >= pendingReviews.length) currentReviewIndex = Math.max(0, pendingReviews.length - 1);
            
            if(pendingReviews.length > 0) {
                updateReviewUI();
            } else {
                loadReviews(); // Refresh to show empty state properly
            }
        } catch(e) {
            showToast("Error al guardar.");
            btnSaveReview.disabled = false;
        }
        btnSaveReview.innerHTML = '<i class="fa-solid fa-save"></i> Guardar y Procesar';
    });

    // --- EXPLORER LOGIC ---
    const btnRefreshExplorer = document.getElementById("btn-refresh-explorer");
    const expFilterDate = document.getElementById("exp-filter-date");
    const expFilterClient = document.getElementById("exp-filter-client");

    if (btnRefreshExplorer) {
        btnRefreshExplorer.addEventListener("click", loadExplorer);
    }
    
    async function loadExplorer() {
        const listContainer = document.getElementById("explorer-list");
        if(!listContainer) return;

        listContainer.innerHTML = '<li class="activity-item empty-state"><p><i class="fa-solid fa-spinner fa-spin"></i> Cargando documentos...</p></li>';
        
        try {
            if(window.pywebview && window.pywebview.api) {
                const dateFilter = expFilterDate ? expFilterDate.value : "";
                const clientFilter = expFilterClient ? expFilterClient.value : "";
                const docs = await window.pywebview.api.get_other_documents(clientFilter, dateFilter);
                
                listContainer.innerHTML = '';
                if(docs.length === 0) {
                    listContainer.innerHTML = '<li class="activity-item empty-state"><p>No se encontraron documentos.</p></li>';
                    return;
                }
                
                docs.forEach(doc => {
                    const icon = doc.type === 'pdf' ? 'fa-file-pdf' : 'fa-file-code';
                    const color = doc.type === 'pdf' ? 'var(--danger)' : 'var(--warning)';
                    const li = document.createElement("li");
                    li.className = "activity-item";
                    li.innerHTML = `
                        <i class="fa-solid ${icon}" style="color: ${color}; font-size: 1.5rem;"></i>
                        <div style="flex:1;">
                            <p style="font-weight:600; font-size:0.9rem;">${doc.name}</p>
                            <span style="font-size:0.75rem; color:var(--text-muted);">${doc.client} | ${doc.date}</span>
                        </div>
                     `;
                     li.addEventListener("click", () => {
                         document.querySelectorAll("#explorer-list .activity-item").forEach(item => item.style.background = 'transparent');
                         li.style.background = 'rgba(92, 126, 143, 0.1)';
                         if(window.pywebview && window.pywebview.api) {
                             window.pywebview.api.open_document(doc.path).then(result => {
                                 showToast(result[1]);
                             }).catch(() => showToast("No se pudo abrir el documento."));
                         }
                     });
                    listContainer.appendChild(li);
                });
            }
        } catch (e) {
            console.error(e);
            listContainer.innerHTML = '<li class="activity-item empty-state"><p>Error al cargar documentos.</p></li>';
        }
    }

    // --- SETTINGS LOGIC ---
    const btnSaveApis = document.getElementById("btn-save-apis");
    if(btnSaveApis) {
        btnSaveApis.addEventListener("click", async () => {
            const deepseekEl = document.getElementById("api-deepseek");
            const geminiEl = document.getElementById("api-gemini");
            const data = {
                deepseek: deepseekEl ? deepseekEl.value : "",
                gemini: geminiEl ? geminiEl.value : ""
            };
            try {
                if(window.pywebview && window.pywebview.api) {
                    await window.pywebview.api.save_settings(data);
                    showToast("Configuración guardada exitosamente");
                    if(data.deepseek) {
                        const status = document.getElementById("deepseek-status");
                        const button = document.getElementById("btn-change-deepseek");
                        if(status) status.style.display = "inline-block";
                        if(button && deepseekEl) { button.style.display = "inline-block"; deepseekEl.disabled = true; }
                    }
                    if(data.gemini) {
                        const geminiStatus = document.getElementById("gemini-status");
                        if(geminiStatus) geminiStatus.style.display = "inline-block";
                        const button = document.getElementById("btn-change-gemini");
                        if(button && geminiEl) { button.style.display = "inline-block"; geminiEl.disabled = true; }
                    }
                }
            } catch (e) {
                showToast("Error al guardar configuración");
            }
        });
    }

    async function loadSettings() {
        try {
            if(window.pywebview && window.pywebview.api) {
                const config = await window.pywebview.api.get_settings();
                const deepseekEl = document.getElementById("api-deepseek");
                const deepseekStatus = document.getElementById("deepseek-status");
                const deepseekButton = document.getElementById("btn-change-deepseek");
                if(config.deepseek && deepseekEl) {
                    deepseekEl.value = config.deepseek;
                    deepseekEl.disabled = true;
                    if(deepseekStatus) deepseekStatus.style.display = "inline-block";
                    if(deepseekButton) deepseekButton.style.display = "inline-block";
                }
                const geminiEl = document.getElementById("api-gemini");
                const geminiStatus = document.getElementById("gemini-status");
                const geminiButton = document.getElementById("btn-change-gemini");
                if(config.gemini && geminiEl) {
                    geminiEl.value = config.gemini;
                    geminiEl.disabled = true;
                    if(geminiStatus) geminiStatus.style.display = "inline-block";
                    if(geminiButton) geminiButton.style.display = "inline-block";
                }
            }
        } catch (e) {
            console.error(e);
        }
    }

    function enableApiChange(inputId, statusId, buttonId) {
        const input = document.getElementById(inputId);
        const status = document.getElementById(statusId);
        const button = document.getElementById(buttonId);
        if(!input || !button) return;
        button.addEventListener("click", () => {
            input.disabled = false;
            input.value = "";
            input.focus();
            if(status) status.style.display = "none";
            button.style.display = "none";
        });
    }

    enableApiChange("api-deepseek", "deepseek-status", "btn-change-deepseek");
    enableApiChange("api-gemini", "gemini-status", "btn-change-gemini");

});
