document.addEventListener("DOMContentLoaded", () => {
    
    // Variables
    const navItems = document.querySelectorAll(".nav-item");
    const views = document.querySelectorAll(".view-container");
    const btnProcess = document.getElementById("btn-process");

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
        loadScopeData();
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

    // --- Alcance del motor: todas las empresas o una empresa ---
    const scopeState = { mode: "all", company: null, counts: {} };
    const scopeAllBtn = document.getElementById("scope-all");
    const scopeOneBtn = document.getElementById("scope-one");
    const scopePicker = document.getElementById("scope-company-picker");
    const scopeSearch = document.getElementById("scope-company-search");
    const scopeList = document.getElementById("scope-company-list");
    const scopeSummary = document.getElementById("scope-summary");
    let engineRunning = false;

    function totalScopeAccounts() {
        return Object.values(scopeState.counts).reduce((sum, n) => sum + n, 0);
    }

    function updateScopeSummary() {
        if(!scopeSummary) return;
        if(scopeState.mode === "one" && scopeState.company) {
            const n = scopeState.counts[scopeState.company] || 0;
            scopeSummary.textContent = `Se procesarán ${n} cuenta${n === 1 ? "" : "s"} de ${scopeState.company}.`;
        } else if(scopeState.mode === "one") {
            scopeSummary.textContent = "Seleccione una empresa para definir el alcance.";
        } else {
            scopeSummary.textContent = `Se procesarán todas las cuentas configuradas (${totalScopeAccounts()}).`;
        }
        if(btnProcess) btnProcess.disabled = engineRunning || (scopeState.mode === "one" && !scopeState.company);
    }

    function renderScopeList(filterText) {
        if(!scopeList) return;
        const query = (filterText || "").toLowerCase();
        const companies = Object.keys(scopeState.counts).sort((a, b) => a.localeCompare(b)).filter(alias => alias.toLowerCase().includes(query));
        scopeList.innerHTML = "";
        if(companies.length === 0) {
            scopeList.innerHTML = '<li class="activity-item empty-state"><p>Sin empresas coincidentes.</p></li>';
            return;
        }
        companies.forEach(alias => {
            const li = document.createElement("li");
            li.className = "activity-item scope-option" + (scopeState.company === alias ? " selected" : "");
            li.tabIndex = 0;
            li.innerHTML = `<strong style="flex:1;">${alias}</strong><span class="badge badge-teal">${scopeState.counts[alias]} cuenta${scopeState.counts[alias] === 1 ? "" : "s"}</span>`;
            const pick = () => {
                scopeState.company = alias;
                renderScopeList(scopeSearch ? scopeSearch.value : "");
                updateScopeSummary();
            };
            li.addEventListener("click", pick);
            li.addEventListener("keypress", (e) => { if(e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); } });
            scopeList.appendChild(li);
        });
    }

    function setScopeMode(mode) {
        scopeState.mode = mode;
        if(scopeAllBtn) scopeAllBtn.classList.toggle("active", mode === "all");
        if(scopeOneBtn) scopeOneBtn.classList.toggle("active", mode === "one");
        if(scopePicker) scopePicker.style.display = mode === "one" ? "" : "none";
        if(mode === "all") scopeState.company = null;
        renderScopeList(scopeSearch ? scopeSearch.value : "");
        updateScopeSummary();
    }

    if(scopeAllBtn) scopeAllBtn.addEventListener("click", () => setScopeMode("all"));
    if(scopeOneBtn) scopeOneBtn.addEventListener("click", () => setScopeMode("one"));
    if(scopeSearch) scopeSearch.addEventListener("input", () => renderScopeList(scopeSearch.value));

    async function loadScopeData() {
        if(!window.pywebview || !window.pywebview.api) return;
        try {
            const [companies, accounts] = await Promise.all([
                window.pywebview.api.get_companies(false),
                window.pywebview.api.get_emails()
            ]);
            const counts = {};
            (companies || []).forEach(c => { counts[c.alias] = 0; });
            (accounts || []).forEach(a => {
                const alias = a.client || "Sin empresa";
                counts[alias] = (counts[alias] || 0) + 1;
            });
            scopeState.counts = counts;
            if(scopeState.company && !(scopeState.company in counts)) scopeState.company = null;
            renderScopeList(scopeSearch ? scopeSearch.value : "");
            updateScopeSummary();
        } catch(e) {
            if(scopeSummary) scopeSummary.textContent = "No se pudo cargar la lista de empresas.";
        }
    }

    // Boton unico Iniciar / Detener (usa el mismo metodo que el pie de pagina).
    if(btnProcess) btnProcess.addEventListener("click", async () => {
        btnProcess.disabled = true;
        const stopping = engineRunning;
        btnProcess.innerHTML = stopping
            ? '<i class="fa-solid fa-spinner fa-spin"></i> Deteniendo...'
            : '<i class="fa-solid fa-spinner fa-spin"></i> Iniciando...';
        try {
            if(!window.pywebview || !window.pywebview.api) {
                showToast("Error: API no disponible.");
                return;
            }
            if(stopping) {
                const result = await window.pywebview.api.stop_processing();
                showToast(result[1]);
            } else {
                const scopeValue = scopeState.mode === "one" ? (scopeState.company || "") : "";
                const message = await window.pywebview.api.start_processing(scopeValue);
                showToast(message);
            }
        } catch(error) {
            showToast("Ocurrió un error al cambiar el estado del motor.");
        } finally {
            updateTelemetry();
        }
    });

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
            // Recordar la ultima carpeta de destino (persistida en settings.json del backend).
            try {
                const settings = await window.pywebview.api.get_settings();
                if(settings && settings.last_excel_dir && !inputPath.value) {
                    inputPath.value = settings.last_excel_dir;
                    checkFormReady();
                }
            } catch(e) {}
        }
    }

    async function refreshExcelDiagnostics() {
        if(!excelDiagnostics || !window.pywebview || !window.pywebview.api || !window.pywebview.api.get_excel_diagnostics) return;
        const diagnostics = await window.pywebview.api.get_excel_diagnostics(selClient.value, selMonth.value);
        const periods = diagnostics.periods.length ? diagnostics.periods.join(", ") : "ninguno";
        const selected = diagnostics.selected_path || diagnostics.client_path || diagnostics.processed_dir;
        excelDiagnostics.textContent = `Ruta activa: ${selected} | Períodos: ${periods} | Documentos del período: ${diagnostics.json_count} | Base: ${diagnostics.database} (${diagnostics.database_exists ? "creada" : "no encontrada"})`;
        const summary = document.getElementById("excel-summary");
        if(summary) {
            const base = `${diagnostics.json_count} documentos, ${diagnostics.pdf_count} con PDF`;
            summary.textContent = (selClient.value && selMonth.value)
                ? base + ((diagnostics.error_count || 0) > 0 ? `, ${diagnostics.error_count} con errores.` : ".")
                : "";
        }
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
        setBusy(btnGenerateExcel, true, "Generando...");
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
                // Recordar la carpeta de destino en el backend (settings.json).
                try {
                    const settings = await window.pywebview.api.get_settings();
                    settings.last_excel_dir = inputPath.value;
                    await window.pywebview.api.save_settings(settings);
                } catch(e) {}
            }
            if(!success && window.pywebview.api.get_excel_diagnostics) {
                const diagnostics = await window.pywebview.api.get_excel_diagnostics(
                    selClient.value, selMonth.value
                );
                excelDiagnostics.textContent = `Ruta activa: ${diagnostics.selected_path || diagnostics.client_path || diagnostics.processed_dir} | Períodos disponibles: ${diagnostics.periods.join(", ") || "ninguno"} | Documentos: ${diagnostics.json_count} | Base: ${diagnostics.database} (${diagnostics.database_exists ? "creada" : "no encontrada"})`;
            }
        } catch (error) {
            showToast("Error al generar el Excel.");
            if(excelDiagnostics) excelDiagnostics.textContent = `Error técnico: ${error}`;
        } finally {
            setBusy(btnGenerateExcel, false);
            checkFormReady();
        }
    });

    // --- TELEMETRIA REAL DEL MOTOR ---
    let telemetryInterval = null;

    function formatHMS(totalSeconds) {
        const s = Math.max(0, Math.floor(totalSeconds || 0));
        const h = String(Math.floor(s / 3600)).padStart(2, "0");
        const m = String(Math.floor((s % 3600) / 60)).padStart(2, "0");
        const sec = String(s % 60).padStart(2, "0");
        return `${h}:${m}:${sec}`;
    }

    function phaseText(tel) {
        const phase = tel.phase || tel.status || "IDLE";
        if(phase === "DESCARGANDO") return `Descargando correos – cuenta ${tel.accounts_done} de ${tel.total_accounts}${tel.current_account ? ` (${tel.current_account})` : ""}`;
        if(phase === "PROCESANDO") return `Procesando documentos – ${tel.docs_done} de ${tel.docs_total}`;
        if(phase === "DURMIENDO") return "En pausa hasta el siguiente ciclo";
        if(phase === "DETENIENDO") return "Deteniendo el motor...";
        return "En espera";
    }
    
    function updateDashActivity(messages) {
        const activity = document.getElementById("dash-activity");
        if(!activity) return;
        if(!messages || messages.length === 0) {
            activity.innerHTML = '<li class="activity-item empty-state"><p>Sin actividad todavía.</p></li>';
            return;
        }
        activity.innerHTML = "";
        messages.slice(-10).reverse().forEach(entry => {
            const li = document.createElement("li");
            li.className = "activity-item";
            const time = (entry.time || "").slice(11, 19) || entry.time || "";
            const text = document.createElement("span");
            text.style.flex = "1";
            text.textContent = entry.message || "";
            const clock = document.createElement("span");
            clock.className = "text-muted";
            clock.style.fontSize = "0.75rem";
            clock.textContent = time;
            li.appendChild(clock);
            li.appendChild(text);
            activity.appendChild(li);
        });
    }


    async function updateTelemetry() {
        if(!window.pywebview || !window.pywebview.api) return;
        try {
            const tel = await window.pywebview.api.get_telemetry();
            const phase = tel.phase || tel.status || "IDLE";
            engineRunning = phase !== "IDLE";

            const pct = tel.progress_percent || 0;
            const fill = document.getElementById("dash-progress-fill");
            const pctEl = document.getElementById("dash-progress-pct");
            const phaseEl = document.getElementById("dash-phase-text");
            if(fill) fill.style.width = `${Math.min(100, Math.max(0, pct))}%`;
            if(pctEl) pctEl.textContent = `${pct}%`;
            if(phaseEl) phaseEl.textContent = phaseText(tel);

            const setCounter = (id, value) => {
                const el = document.getElementById(id);
                if(el) el.textContent = value;
            };
            setCounter("c-downloaded", tel.docs_downloaded);
            setCounter("c-processed", tel.docs_processed);
            setCounter("c-duplicates", tel.duplicates || 0);
            setCounter("c-errors", tel.errors);

            const uptimeEl = document.getElementById("dash-uptime");
            if(uptimeEl) uptimeEl.textContent = "Uptime: " + formatHMS(tel.uptime_seconds);

            updateDashActivity(tel.recent_messages);

            if(btnProcess) {
                if(engineRunning) {
                    btnProcess.innerHTML = '<i class="fa-solid fa-stop"></i> Detener';
                } else {
                    btnProcess.innerHTML = '<i class="fa-solid fa-play"></i> Iniciar';
                }
            }
            const stopButton = document.getElementById("btn-stop-process");
            const closeButton = document.getElementById("btn-close-app");
            if(stopButton) stopButton.disabled = !engineRunning;
            if(closeButton) closeButton.disabled = engineRunning;
            [scopeSearch, scopeAllBtn, scopeOneBtn].forEach(el => { if(el) el.disabled = engineRunning; });
            updateScopeSummary();
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

    // Modal de confirmación reutilizable: showConfirm(title, message, danger) -> Promise<boolean>.
    // Reemplaza al confirm() nativo en toda la app.
    let modalResolve = null;
    function showConfirm(title, message, danger) {
        const overlay = document.getElementById("modal-overlay");
        const titleEl = document.getElementById("modal-title");
        const messageEl = document.getElementById("modal-message");
        const okBtn = document.getElementById("modal-ok");
        const cancelBtn = document.getElementById("modal-cancel");
        if(!overlay || !okBtn || !cancelBtn) return Promise.resolve(false);
        titleEl.textContent = title || "Confirmar";
        messageEl.textContent = message || "";
        okBtn.className = "btn " + (danger === false ? "btn-primary" : "btn-danger");
        overlay.style.display = "flex";
        const previouslyFocused = document.activeElement;
        cancelBtn.focus();
        return new Promise((resolve) => {
            const done = (value) => {
                overlay.style.display = "none";
                okBtn.onclick = null;
                cancelBtn.onclick = null;
                overlay.onclick = null;
                document.removeEventListener("keydown", onKey);
                modalResolve = null;
                if(previouslyFocused && previouslyFocused.focus) previouslyFocused.focus();
                resolve(value);
            };
            modalResolve = done;
            okBtn.onclick = () => done(true);
            cancelBtn.onclick = () => done(false);
            overlay.onclick = (e) => { if(e.target === overlay) done(false); };
            const onKey = (e) => {
                if(e.key === "Escape") done(false);
                else if(e.key === "Enter" && document.activeElement !== cancelBtn) done(true);
                else if(e.key === "Tab") {
                    // Trampa de foco simple dentro del modal.
                    if(e.shiftKey && document.activeElement === cancelBtn) { e.preventDefault(); okBtn.focus(); }
                    else if(!e.shiftKey && document.activeElement === okBtn) { e.preventDefault(); cancelBtn.focus(); }
                }
            };
            document.addEventListener("keydown", onKey);
        });
    }

    // Botones con estado "ocupado": spinner + disabled, restaurados siempre en finally.
    function setBusy(btn, busy, busyLabel) {
        if(!btn) return;
        if(busy) {
            if(btn.dataset.originalHtml === undefined) btn.dataset.originalHtml = btn.innerHTML;
            btn.disabled = true;
            btn.innerHTML = `<i class="fa-solid fa-spinner fa-spin"></i> ${busyLabel || "Procesando..."}`;
        } else {
            btn.disabled = false;
            if(btn.dataset.originalHtml !== undefined) btn.innerHTML = btn.dataset.originalHtml;
        }
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
                    const confirmed = await showConfirm(
                        "Eliminar respaldo",
                        `Se eliminarán los archivos del respaldo '${alias}'. Esta acción no se puede deshacer.`
                    );
                    if(!confirmed) return;
                    setBusy(btn, true, "Eliminando...");
                    try {
                        const res = await window.pywebview.api.delete_client_data(alias, true, false);
                        showToast(res[1]);
                        if(res[0]) { loadRecoveryBackups(); }
                    } catch(e) {
                        showToast("Error al eliminar el respaldo.");
                    } finally {
                        setBusy(btn, false);
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
            const confirmed = await showConfirm(
                "Cerrar aplicación",
                "¿Cerrar Oculus? El motor debe estar detenido.",
                false
            );
            if(!confirmed) return;
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
                                    <small class="text-muted">${em.client || 'Sin cliente'} - ${em.server} · sync: ${em.last_sync || 'nunca'}</small>
                                </div>
                            </div>
                            <div style="display: flex; gap: 10px; align-items: center;">
                                <span class="badge protocol-chip">${em.port === 995 ? 'POP3 995' : 'IMAP ' + em.port}</span>
                                <span class="badge ${em.active ? 'badge-teal' : 'bg-danger'}">${em.active ? 'Activa' : 'Con error de conexión'}</span>
                                <button class="icon-btn btn-edit-account" data-email="${em.email}" title="Editar Cuenta" aria-label="Editar cuenta ${em.email}"><i class="fa-solid fa-pen"></i></button>
                                <button class="icon-btn btn-delete-account" data-email="${em.email}" title="Eliminar Cuenta" aria-label="Eliminar cuenta ${em.email}" style="color: var(--danger);"><i class="fa-solid fa-trash"></i></button>
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
                            
                            document.getElementById("email-password").value = "";
                        }
                    });
                });
                
                document.querySelectorAll(".btn-delete-account").forEach(btn => {
                    btn.addEventListener("click", async () => {
                        const email = btn.getAttribute("data-email");
                        const confirmed = await showConfirm(
                            "Eliminar cuenta",
                            `¿Eliminar la cuenta ${email}? Dejará de monitorearse.`
                        );
                        if(!confirmed) return;
                        setBusy(btn, true, "Eliminando...");
                        try {
                            const res = await window.pywebview.api.delete_email(email);
                            showToast(res[1]);
                            loadEmails();
                        } catch(e) {
                            showToast("Error al eliminar la cuenta");
                        } finally {
                            setBusy(btn, false);
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
        const email = document.getElementById("email-address").value.trim();
        let provider = document.getElementById("email-provider").value;
        if(provider === "custom") provider = document.getElementById("custom-imap-server").value;
        const pass = document.getElementById("email-password").value;
        const portVal = document.getElementById("email-port") ? document.getElementById("email-port").value : "993";
        const port = parseInt(portVal, 10) || 993;
        const startDate = document.getElementById("email-start-date").value || "2026-05-01";

        if(!client || !email || !provider) {
            showToast("Seleccione una empresa y complete los campos obligatorios.");
            return;
        }
        if(!/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email)) {
            showToast("Formato de correo inválido.");
            return;
        }
        if(port < 1 || port > 65535) {
            showToast("Puerto fuera de rango (1-65535).");
            return;
        }
        if(!oldEmail && !pass) {
            showToast("La contraseña es obligatoria para cuentas nuevas.");
            return;
        }

        setBusy(btnAddEmail, true, "Registrando...");

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
        } finally {
            setBusy(btnAddEmail, false);
        }
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

        setBusy(btnSaveReview, true, "Guardando...");

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
        } finally {
            setBusy(btnSaveReview, false);
        }
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
            const llamaparseEl = document.getElementById("api-llamaparse");
            const data = {
                deepseek: deepseekEl ? deepseekEl.value : "",
                gemini: geminiEl ? geminiEl.value : "",
                llamaparse: llamaparseEl ? llamaparseEl.value : ""
            };
            // Conservar claves de UI (p. ej. last_excel_dir) al guardar.
            try {
                if(window.pywebview && window.pywebview.api && window.pywebview.api.get_settings) {
                    const current = await window.pywebview.api.get_settings();
                    if(current && current.last_excel_dir) data.last_excel_dir = current.last_excel_dir;
                }
            } catch(e) {}
            setBusy(btnSaveApis, true, "Guardando...");
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
                    if(data.llamaparse) {
                        const lpStatus = document.getElementById("llamaparse-status");
                        if(lpStatus) lpStatus.style.display = "inline-block";
                        const button = document.getElementById("btn-change-llamaparse");
                        if(button && llamaparseEl) { button.style.display = "inline-block"; llamaparseEl.disabled = true; }
                    }
                }
            } catch (e) {
                showToast("Error al guardar configuración");
            } finally {
                setBusy(btnSaveApis, false);
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
                const llamaparseEl = document.getElementById("api-llamaparse");
                const llamaparseStatus = document.getElementById("llamaparse-status");
                const llamaparseButton = document.getElementById("btn-change-llamaparse");
                if(config.llamaparse && llamaparseEl) {
                    llamaparseEl.value = config.llamaparse;
                    llamaparseEl.disabled = true;
                    if(llamaparseStatus) llamaparseStatus.style.display = "inline-block";
                    if(llamaparseButton) llamaparseButton.style.display = "inline-block";
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
    enableApiChange("api-llamaparse", "llamaparse-status", "btn-change-llamaparse");

});
