import os
import re
import datetime
import json
from pathlib import Path
from imap_tools import MailBox, AND
from src.backend.utils.config import CARPETA_ADJUNTOS_OTROS

class EmailService:
    def __init__(self, download_dir: str, other_attachments_dir: str = None):
        self.download_dir = Path(download_dir)
        self.download_dir.mkdir(parents=True, exist_ok=True)
        self.other_attachments_dir = Path(other_attachments_dir) if other_attachments_dir else CARPETA_ADJUNTOS_OTROS
        
        # Palabras maestras para detectar DTEs con asuntos raros
        self.palabras_clave_asunto = [
            "dte", "documento", "facturacion", "facturación", 
            "credito fiscal", "crédito fiscal", "ccf",
            "factura", "comprobante", "emisión", "emision", "adjunto", "envio",
            "autofacil", "recibo", "nota"
        ]
        
    def _asunto_coincide(self, asunto: str) -> bool:
        """Ya no filtramos por asunto para evitar perder DTEs con asuntos no estándar."""
        return True

    def _nombre_seguro(self, nombre: str) -> str:
        # Extraer el nombre base y la extensión
        partes = nombre.rsplit('.', 1)
        if len(partes) == 2:
            base, ext = partes
            base_limpia = re.sub(r"[^A-Za-z0-9_.-]", "_", base)
            return f"{base_limpia}.{ext}"
        else:
            return re.sub(r"[^A-Za-z0-9_.-]", "_", nombre)

    def _procesar_mensaje_generico(self, cuenta: str, uid: str, subject: str, msg_date: datetime.datetime, adjuntos_raw: list, resultados: dict):
        """Descarga cruda y segura usando el UID del correo y nombre original."""
        if not self._asunto_coincide(subject):
            return
            
        # Filtrar extensiones válidas
        adjuntos = []
        adjuntos_otros = []
        for index, att in enumerate(adjuntos_raw, start=1):
            filename = str(att.get('filename') or '')
            content_type = str(att.get('content_type') or '').lower()
            payload = att.get('payload') or b''
            extension = Path(filename).suffix.lower()
            if extension not in {'.pdf', '.json'}:
                if 'pdf' in content_type or payload.startswith(b'%PDF'):
                    filename = f'{Path(filename).stem or uid}_{index}.pdf'
                elif 'json' in content_type or payload.lstrip().startswith((b'{', b'[')):
                    filename = f'{Path(filename).stem or uid}_{index}.json'
                else:
                    adjuntos_otros.append(att)
                    continue
            att = dict(att)
            att['filename'] = filename
            adjuntos.append(att)
        for index, att in enumerate(adjuntos_otros, start=1):
            filename = self._nombre_seguro(str(att.get('filename') or f'{uid}_{index}.bin'))
            target_dir = self.other_attachments_dir / cuenta / msg_date.strftime('%Y-%m')
            target_dir.mkdir(parents=True, exist_ok=True)
            destination = target_dir / filename
            suffix = 1
            while destination.exists():
                destination = target_dir / f'{Path(filename).stem}_{suffix}{Path(filename).suffix}'
                suffix += 1
            destination.write_bytes(att.get('payload') or b'')
            resultados["adjuntos_otros"] = resultados.get("adjuntos_otros", 0) + 1
            print(f'  [i] Adjunto no procesable conservado: {destination.name}')
        if not adjuntos:
            nombres = [att.get('filename') or '<sin nombre>' for att in adjuntos_raw]
            print(f"  [!] Correo UID {uid}: no hay adjuntos PDF/JSON para procesar. Adjuntos: {nombres or 'ninguno'}")
            return
            
        fecha_str = msg_date.strftime("%d%m%Y")
        cuenta_upper = cuenta.upper()
        
        for att in adjuntos:
            nombre_original_limpio = self._nombre_seguro(att['filename'])
            # Estructura: ALIAS_UID_FECHA_nombreoriginal.ext
            nombre_final = f"{cuenta_upper}_{uid}_{fecha_str}_{nombre_original_limpio}"
            ruta_destino = self.download_dir / nombre_final
            
            # Anti-colisión por si por alguna locura el mismo correo trae dos archivos llamados igual
            contador = 1
            while ruta_destino.exists():
                partes = nombre_final.rsplit('.', 1)
                if len(partes) == 2:
                    nombre_final = f"{partes[0]}_{contador}.{partes[1]}"
                else:
                    nombre_final = f"{nombre_final}_{contador}"
                ruta_destino = self.download_dir / nombre_final
                contador += 1
                
            with open(ruta_destino, "wb") as f:
                f.write(att['payload'])
                
            resultados["descargados"] += 1
            print(f"  [+] Descargado: {nombre_final}")

    def descargar_correos(self, cuenta: str, servidor: str, puerto: int, usuario: str, password: str, carpeta: str = "INBOX", protocolo: str = "IMAP", estado_key: str = None, start_date: str = "2026-05-01", end_date: str = None, should_stop=None):
        """Punto de entrada principal para IMAP o POP3."""
        print(f"[*] Iniciando descarga ({protocolo}) para {usuario} en {servidor}")
        estado_key = estado_key or usuario
        if protocolo.upper() == "POP3":
            return self._descargar_pop3(cuenta, servidor, puerto, usuario, password, estado_key, start_date, end_date, should_stop)
        else:
            return self._descargar_imap(cuenta, servidor, puerto, usuario, password, carpeta, estado_key, start_date, end_date, should_stop)

    def _descargar_imap(self, cuenta: str, servidor: str, puerto: int, usuario: str, password: str, carpeta: str, estado_key: str, start_date: str, end_date: str = None, should_stop=None):
        resultados = {"revisados": 0, "descargados": 0, "errores": 0}
        try:
            fecha_corte = datetime.date.fromisoformat(start_date)
        except (TypeError, ValueError):
            print(f"  [!] Fecha invalida para '{cuenta}', usando 2026-05-01")
            fecha_corte = datetime.date(2026, 5, 1)
        
        mailbox = None
        intentos = 0
        max_intentos = 3
        while intentos < max_intentos:
            try:
                mailbox = MailBox(servidor, port=puerto, timeout=60).login(usuario, password, initial_folder=carpeta)
                # Gmail puede archivar mensajes dentro de conversaciones y sacarlos
                # de INBOX. All Mail permite revisar esos mensajes tambien.
                if "gmail" in servidor.lower():
                    try:
                        all_mail = next(
                            (folder.name for folder in mailbox.folder.list()
                             if folder.name.lower() in {"[gmail]/all mail", "all mail", "todos los mensajes"}),
                            None,
                        )
                        if all_mail:
                            mailbox.folder.set(all_mail)
                            print(f"  [*] Gmail: revisando carpeta {all_mail}")
                    except Exception as folder_error:
                        print(f"  [!] No se pudo seleccionar Todos los mensajes de Gmail: {folder_error}")
                break  # Conexión exitosa
            except Exception as e:
                intentos += 1
                print(f"  [!] Intento {intentos}/{max_intentos} falló para '{cuenta}' (IMAP): {e}")
                if intentos >= max_intentos:
                    raise e
                import time
                time.sleep(5)
                
        estado_file = self.download_dir / "sync_estado.json"
        estado_descargas = {}
        if estado_file.exists():
            try:
                with open(estado_file, "r") as f:
                    estado_descargas = json.load(f)
            except: pass
            
        # Versiones anteriores usaban el alias como clave. Migrarlo una vez
        # evita redescargar la primera cuenta sin mezclar los buzones.
        if estado_key not in estado_descargas:
            estado_descargas[estado_key] = estado_descargas.pop(cuenta, [])

        try:
            criterio_args = {"date_gte": fecha_corte}
            if end_date:
                criterio_args["date_lt"] = datetime.date.fromisoformat(end_date)
            criterio = AND(**criterio_args)

            try:
                for msg in mailbox.fetch(criterio, mark_seen=False):
                    if str(msg.uid) in estado_descargas[estado_key]:
                        continue

                    resultados["revisados"] += 1
                    try:
                        adjuntos_raw = [{'filename': att.filename, 'content_type': att.content_type, 'payload': att.payload} for att in msg.attachments]

                        dt = msg.date if msg.date else datetime.datetime.now()
                        antes = resultados["descargados"] + resultados.get("adjuntos_otros", 0)
                        self._procesar_mensaje_generico(cuenta, msg.uid, msg.subject, dt, adjuntos_raw, resultados)

                        if resultados["descargados"] + resultados.get("adjuntos_otros", 0) > antes:
                            estado_descargas[estado_key].append(str(msg.uid))
                        if should_stop and should_stop():
                            break
                    except Exception as ex:
                        print(f"  [!] Error procesando correo IMAP UID {msg.uid}: {ex}")
                        resultados["errores"] += 1
            finally:
                # Guardar progreso aunque haya error a mitad del bucle.
                try:
                    with open(estado_file, "w") as f:
                        json.dump(estado_descargas, f)
                except Exception as save_error:
                    print(f"  [!] No se pudo guardar sync_estado.json: {save_error}")
                try:
                    if mailbox is not None:
                        mailbox.logout()
                except Exception:
                    pass
        except Exception as e:
            print(f"[!] Error IMAP en {cuenta}: {e}")
            raise e

        return resultados

    def _descargar_pop3(self, cuenta: str, servidor: str, puerto: int, usuario: str, password: str, estado_key: str, start_date: str, end_date: str = None, should_stop=None):
        import poplib
        import email
        import email.utils
        
        resultados = {"revisados": 0, "descargados": 0, "errores": 0}
        try:
            start_date_value = datetime.date.fromisoformat(start_date)
        except (TypeError, ValueError):
            print(f"  [!] Fecha invalida para '{cuenta}', usando 2026-05-01")
            start_date_value = datetime.date(2026, 5, 1)
        fecha_corte = datetime.datetime.combine(
            start_date_value,
            datetime.time.min,
            tzinfo=datetime.timezone.utc,
        )
        fecha_fin = datetime.datetime.combine(
            datetime.date.fromisoformat(end_date), datetime.time.min, tzinfo=datetime.timezone.utc
        ) if end_date else None
        
        estado_file = self.download_dir / "sync_estado.json"
        estado_descargas = {}
        if estado_file.exists():
            try:
                with open(estado_file, "r") as f:
                    estado_descargas = json.load(f)
            except: pass
            
        if estado_key not in estado_descargas:
            estado_descargas[estado_key] = estado_descargas.pop(cuenta, [])
            
        conn = None
        intentos = 0
        max_intentos = 3
        while intentos < max_intentos:
            try:
                conn = poplib.POP3_SSL(servidor, puerto)
                conn.user(usuario)
                conn.pass_(password)
                break  # Conexión exitosa
            except Exception as e:
                intentos += 1
                print(f"  [!] Intento {intentos}/{max_intentos} falló para '{cuenta}' (POP3): {e}")
                if intentos >= max_intentos:
                    raise e
                import time
                time.sleep(5)
                
        try:
            # Obtener UIDs estables del servidor
            resp, items, octets = conn.uidl()
            uidls = {}
            for item in items:
                idx, uid = item.decode().split(' ')
                uidls[int(idx)] = uid

            num_msgs = len(conn.list()[1])
            print(f"  [POP3] {num_msgs} mensajes en el servidor.")

            try:
                for i in range(1, num_msgs + 1):
                    uid = uidls.get(i, str(i))

                    if uid in estado_descargas[estado_key]:
                        continue

                    resultados["revisados"] += 1

                    # Descargar mensaje de forma segura
                    try:
                        _, lineas, _ = conn.retr(i)
                        raw_email = b'\r\n'.join(lineas)
                        msg = email.message_from_bytes(raw_email)

                        date_str = msg.get("Date")
                        if date_str:
                            dt = email.utils.parsedate_to_datetime(date_str)
                            if dt.tzinfo is None:
                                dt = dt.replace(tzinfo=datetime.timezone.utc)
                            if dt < fecha_corte:
                                estado_descargas[estado_key].append(uid)
                                continue
                            if fecha_fin and dt >= fecha_fin:
                                estado_descargas[estado_key].append(uid)
                                continue
                        else:
                            dt = datetime.datetime.now()

                        subject = str(msg.get("Subject", ""))

                        adjuntos_raw = []
                        for part in msg.walk():
                            if part.get_content_maintype() == 'multipart': continue
                            filename = part.get_filename()
                            if not filename: continue
                            payload = part.get_payload(decode=True)
                            if payload:
                                adjuntos_raw.append({'filename': filename, 'content_type': part.get_content_type(), 'payload': payload})

                        antes = resultados["descargados"] + resultados.get("adjuntos_otros", 0)
                        self._procesar_mensaje_generico(cuenta, uid, subject, dt, adjuntos_raw, resultados)
                        if resultados["descargados"] + resultados.get("adjuntos_otros", 0) > antes:
                            estado_descargas[estado_key].append(uid)
                        if should_stop and should_stop():
                            break

                    except Exception as ex:
                        print(f"  [!] Error procesando correo UID {uid}: {ex}")
                        # No añadimos a estado_descargas para que intente de nuevo en el futuro, o podríamos añadirlo para saltarlo
                        resultados["errores"] += 1
            finally:
                # Guardar progreso aunque haya error a mitad del bucle.
                try:
                    with open(estado_file, "w") as f:
                        json.dump(estado_descargas, f)
                except Exception as save_error:
                    print(f"  [!] No se pudo guardar sync_estado.json: {save_error}")
                try:
                    if conn is not None:
                        conn.quit()
                except Exception:
                    pass

        except Exception as e:
            print(f"[!] Error POP3 en {cuenta}: {e}")
            raise e

        return resultados
