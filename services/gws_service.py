import os
import json
import subprocess
import asyncio
import asyncio.subprocess
from typing import Dict, Any, List, Optional
from utils.logger import get_logger

logger = get_logger("gws_service")


class GoogleAuthError(Exception):
    """Excepción lanzada cuando hay un error crítico de autenticación."""
    pass


class GoogleWorkspaceService:
    """
    Service to interact with Google Workspace using the gws CLI.
    """

    def _load_credentials_from_env(self):
        """Carga token.json desde variable de entorno en Railway."""
        import base64
        import os
        token_b64 = os.environ.get("GOOGLE_TOKEN_BASE64", "")
        if not token_b64:
            return
        try:
            token_json = base64.b64decode(token_b64).decode('utf-8')
            token_path = os.path.join(
                os.path.dirname(os.path.dirname(__file__)),
                'credentials', 'token.json'
            )
            os.makedirs(os.path.dirname(token_path), exist_ok=True)
            with open(token_path, 'w') as f:
                f.write(token_json)
            logger.info("Credenciales Google cargadas desde variable de entorno")
        except Exception as e:
            logger.error(f"Error cargando credenciales desde env: {e}")

    def __init__(self):
        self._load_credentials_from_env()
        from config import settings
        import os as _os
        _creds = settings.gws_credentials_file
        if not _creds:
            _creds = _os.path.join(
                _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__))),
                "credentials", "token.json"
            )
        self.credentials_path = _os.path.abspath(_creds)
        logger.info(f"credentials_path: {self.credentials_path}")
        import shutil
        import os
        # Buscar gws en múltiples paths posibles
        gws_candidates = [
            shutil.which("gws"),
            "/nix/var/nix/profiles/default/bin/gws",
            "/root/.local/bin/gws",
            "/root/.npm-global/bin/gws",
            "/app/.npm-global/bin/gws",
            "/usr/local/bin/gws",
            "/usr/bin/gws",
        ]
        gws_bin = next(
            (p for p in gws_candidates if p and os.path.exists(p)),
            None
        )
        npx_candidates = [
            shutil.which("npx"),
            "/nix/var/nix/profiles/default/bin/npx",
            "/usr/bin/npx",
            "/usr/local/bin/npx",
        ]
        self.npx_bin = next(
            (p for p in npx_candidates if p and os.path.exists(p)),
            "npx"  # último fallback
        )
        logger.info(f"npx path: {self.npx_bin}")

        if gws_bin:
            logger.info(f"gws encontrado en: {gws_bin}")
            self.npx_gws = [gws_bin]
        else:
            logger.warning("gws no encontrado en paths conocidos, usando npx como fallback")
            self.npx_gws = [self.npx_bin, "--yes", "@googleworkspace/cli"]

        if self.credentials_path and not os.path.exists(self.credentials_path):
            logger.warning(
                f"Credentials not found at {self.credentials_path}"
            )

    def _ensure_token_format(self):
        """Verifica que token.json tiene el campo 'type'. Lo añade si no lo tiene."""
        if not self.credentials_path or not os.path.exists(self.credentials_path):
            return

        try:
            with open(self.credentials_path, 'r') as f:
                data = json.load(f)

            if "type" not in data:
                data["type"] = "authorized_user"
                with open(self.credentials_path, 'w') as f:
                    json.dump(data, f)
                logger.info("Añadido automáticamente el campo 'type' a token.json")
        except Exception as e:
            logger.error(f"Error verificando formato de token: {e}")

    async def _handle_response(
        self,
        process: asyncio.subprocess.Process,
        stdout: bytes,
        stderr: bytes
    ) -> Dict[str, Any]:
        if process.returncode != 0:
            error_msg = stderr.decode().strip()
            logger.error(
                f"gws command failed with code {process.returncode}: {error_msg}"
            )

            if process.returncode == 2 and "auth" in error_msg.lower():
                raise GoogleAuthError(error_msg)

            try:
                return {"error": json.loads(stdout.decode()) if stdout else error_msg}
            except Exception:
                return {"error": error_msg}

        try:
            return json.loads(stdout.decode())
        except json.JSONDecodeError:
            return {"raw": stdout.decode()}

    def _sanitize_params(self, params: Any) -> Any:
        """Convierte floats que son enteros a int (ej: 1.0 -> 1) para la API de Google."""
        if isinstance(params, dict):
            return {k: self._sanitize_params(v) for k, v in params.items()}
        elif isinstance(params, list):
            return [self._sanitize_params(v) for v in params]
        elif isinstance(params, float):
            return int(params) if params.is_integer() else params
        return params

    def _truncate_data(self, data: Any, limit: int = 1000) -> Any:
        """Trunca cadenas largas para ahorrar tokens."""
        if isinstance(data, str):
            if len(data) > limit:
                return data[:limit] + "... [TRUNCADO]"
            return data
        elif isinstance(data, dict):
            return {k: self._truncate_data(v, limit) for k, v in data.items()}
        elif isinstance(data, list):
            return [self._truncate_data(v, limit) for v in data]
        return data

    async def run_command(
        self,
        resource: str,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Runs a gws command."""
        self._ensure_token_format()

        env = os.environ.copy()
        creds_abs = os.path.abspath(self.credentials_path)
        env["GOOGLE_WORKSPACE_CLI_CREDENTIALS_FILE"] = creds_abs
        logger.info(f"Using credentials: {creds_abs} (exists={os.path.exists(creds_abs)})")
        env["GOOGLE_WORKSPACE_CLI_KEYRING_BACKEND"] = "file"
        env["PATH"] = (
            "/root/.local/bin:/root/.npm-global/bin:"
            "/app/.npm-global/bin:/usr/local/bin:"
        ) + env.get("PATH", "")

        subcommands = resource.split(".") + method.split(".")
        cmd = self.npx_gws + subcommands

        if params:
            params = self._sanitize_params(params)
            cmd.extend(["--params", json.dumps(params)])

        if data:
            data = self._sanitize_params(data)
            cmd.extend(["--json", json.dumps(data)])

        logger.info(f"Running gws command: {' '.join(cmd)}")

        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=env
            )

            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=30.0
            )
            return await self._handle_response(process, stdout, stderr)

        except asyncio.TimeoutError:
            try:
                process.kill()
            except ProcessLookupError:
                pass
            logger.error(f"Timeout (30s) ejecutando gws command: {' '.join(cmd)}")
            return {"error": "Timeout executing command."}
        except GoogleAuthError as e:
            msg = (
                "ERROR DE AUTENTICACION: Tu token de Google ha expirado o es inválido. "
                "Esto ocurre comúnmente porque la app está en modo 'Testing' en Google Cloud y caduca cada 7 días. "
                "Para solucionarlo PARA SIEMPRE: Ve a Google Cloud Console > "
                "APIs & Services > OAuth consent screen > Haz click en 'Publish App' (Publicar/En producción). "
                "Luego genera un token nuevo y actualiza GOOGLE_TOKEN_BASE64."
            )
            logger.error(f"Autenticación fallida: {e}")
            return {"error": msg}
        except Exception as e:
            logger.error(f"Error executing subprocess gws: {e}")
            return {"error": str(e)}

    # --- Gmail Methods ---

    async def list_messages(self, query: str = "is:unread", max_results: int = 10) -> List[str]:
        """List Gmail messages based on a query. Returns a clean list of strings with snippets."""
        result = await self.run_command("gmail", "users.messages.list", params={
            "userId": "me",
            "q": query,
            "maxResults": max_results
        })

        if "error" in result:
            return [f"⚠️ {result['error']}"]

        if "messages" not in result or not result["messages"]:
            return []

        messages = result.get("messages", [])
        # Obtener snippets para los primeros 5 para dar contexto al LLM
        to_fetch = messages[:5]
        
        async def fetch_snippet(msg):
            m_id = msg.get("id")
            detail = await self.run_command("gmail", "users.messages.get", params={
                "userId": "me",
                "id": m_id,
                "format": "minimal"
            })
            snip = detail.get("snippet", "Sin resumen").replace("\n", " ")
            return f"ID: {m_id} | Resumen: {snip[:150]}"

        tasks = [fetch_snippet(m) for m in to_fetch]
        clean_list = list(await asyncio.gather(*tasks))

        # Añadir el resto solo como IDs si hay más
        for msg in messages[5:]:
            clean_list.append(f"ID: {msg.get('id')} | (Usa get_email_content para leer)")

        return clean_list

    async def get_message(self, message_id: str) -> Dict[str, Any]:
        """Get details of a specific Gmail message by ID."""
        result = await self.run_command("gmail", "users.messages.get", params={
            "userId": "me",
            "id": message_id
        })

        payload = result.get("payload", {})
        headers = payload.get("headers", [])

        subject = next(
            (h["value"] for h in headers if h["name"].lower() == "subject"),
            "Sin asunto"
        )
        sender = next(
            (h["value"] for h in headers if h["name"].lower() == "from"),
            "Desconocido"
        )
        snippet = result.get("snippet", "")

        has_attachments = False

        def check_attachments(parts):
            nonlocal has_attachments
            if not parts or has_attachments:
                return
            for part in parts:
                if part.get("filename"):
                    has_attachments = True
                    return
                if "parts" in part:
                    check_attachments(part["parts"])

        check_attachments(payload.get("parts", []))

        return {
            "from": sender,
            "subject": subject,
            "has_attachments": has_attachments,
            "snippet": snippet[:500]
        }

    async def send_email(self, to: str, subject: str, body: str) -> Dict[str, Any]:
        """Send a new email message."""
        import base64
        from email.mime.text import MIMEText

        message = MIMEText(body)
        message['to'] = to
        message['subject'] = subject
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')

        return await self.run_command(
            "gmail", "users.messages.send",
            params={"userId": "me"},
            data={"raw": raw}
        )

    def _normalize_datetime(self, dt_str: str) -> str:
        """
        Asegura que una fecha tenga zona horaria.
        Si no tiene offset ni Z, añade +01:00 (Madrid).
        """
        if not dt_str:
            return dt_str
        # Reemplazar espacio por T si el LLM genera "2026-04-07 10:00:00"
        if len(dt_str) > 10 and dt_str[10] == " ":
            dt_str = dt_str[:10] + "T" + dt_str[11:]
        # Ya tiene zona horaria
        if dt_str.endswith("Z") or "+" in dt_str[10:] or dt_str.count("-") > 2:
            return dt_str
        # Añadir offset de Madrid
        return dt_str + "+01:00"

    # --- Calendar Methods ---
    async def list_events(
        self,
        time_min: Optional[str] = None,
        time_max: Optional[str] = None,
        max_results: int = 10
    ) -> Dict[str, Any]:
        """List Google Calendar events."""
        params = {"calendarId": "primary", "maxResults": max_results}
        if time_min:
            params["timeMin"] = self._normalize_datetime(time_min)
        if time_max:
            params["timeMax"] = self._normalize_datetime(time_max)
        if not time_min and not time_max:
            # Si no se pasa nada, usar ahora como mínimo
            from datetime import datetime
            import pytz
            madrid_tz = pytz.timezone('Europe/Madrid')
            now = datetime.now(madrid_tz)
            params["timeMin"] = now.strftime("%Y-%m-%dT%H:%M:%S%z")
        return await self.run_command("calendar", "events.list", params=params)

    async def create_event(
        self,
        summary: str,
        start_time: str,
        end_time: str,
        description: str = ""
    ) -> Dict[str, Any]:
        """Create a new event in Google Calendar."""
        event_data = {
            "summary": summary,
            "description": description,
            "start": {
                "dateTime": self._normalize_datetime(start_time),
                "timeZone": "Europe/Madrid"
            },
            "end": {
                "dateTime": self._normalize_datetime(end_time),
                "timeZone": "Europe/Madrid"
            }
        }
        return await self.run_command(
            "calendar", "events.insert",
            params={"calendarId": "primary"},
            data=event_data
        )

    # --- Docs Methods ---

    async def create_document(
        self,
        title: str,
        text_content: Optional[str] = None
    ) -> Dict[str, Any]:
        """Creates a new Google Doc and optionally inserts text."""
        doc_result = await self.run_command(
            "docs", "documents.create", data={"title": title}
        )
        if "error" in doc_result:
            return doc_result

        doc_id = doc_result.get("documentId")
        if not doc_id or not text_content:
            if doc_id:
                doc_result["url"] = f"https://docs.google.com/document/d/{doc_id}/edit"
            return doc_result

        requests = [
            {
                "insertText": {
                    "location": {"index": 1},
                    "text": text_content
                }
            }
        ]

        await self.run_command(
            "docs", "documents.batchUpdate",
            params={"documentId": doc_id},
            data={"requests": requests}
        )

        doc_result["url"] = f"https://docs.google.com/document/d/{doc_id}/edit"
        return doc_result

    async def read_document(self, document_id: str) -> Dict:
        """Lee el contenido de un Google Doc usando run_command."""
        try:
            result = await self.run_command(
                "docs", "documents.get",
                params={"documentId": document_id}
            )
            if "error" in result:
                return {"error": result["error"], "text": ""}

            # Extraer texto plano del documento
            content = result.get("body", {}).get("content", [])
            text_parts = []
            for element in content:
                paragraph = element.get("paragraph")
                if paragraph:
                    for part in paragraph.get("elements", []):
                        text_run = part.get("textRun")
                        if text_run:
                            text_parts.append(
                                text_run.get("content", "")
                            )

            full_text = "".join(text_parts).strip()
            title = result.get("title", "Sin título")
            logger.info(
                f"Google Doc leído: '{title}' "
                f"({len(full_text)} caracteres)"
            )
            return {
                "title": title,
                "text": full_text,
                "document_id": document_id,
                "url": f"https://docs.google.com/document/d/{document_id}/edit"
            }
        except Exception as e:
            logger.error(f"Error leyendo Google Doc {document_id}: {e}")
            return {"error": str(e), "text": ""}

    async def create_cv_document(
        self, title: str, content: str
    ) -> Dict:
        """Crea un Google Doc con el CV mejorado."""
        try:
            result = await self.create_document(
                title=title,
                text_content=content
            )
            return result
        except Exception as e:
            logger.error(f"Error creando CV doc: {e}")
            return {"error": str(e)}

    # --- Slides Methods ---

    async def create_presentation(self, title: str) -> Dict[str, Any]:
        """Creates a new Google Slides presentation."""
        slide_result = await self.run_command(
            "slides", "presentations.create", data={"title": title}
        )
        if "error" in slide_result:
            return slide_result

        presentation_id = slide_result.get("presentationId")
        if presentation_id:
            slide_result["url"] = (
                f"https://docs.google.com/presentation/d/{presentation_id}/edit"
            )

        return slide_result
