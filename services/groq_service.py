import json
from typing import List, Dict, Any
from groq import AsyncGroq
from openai import AsyncOpenAI
from config import settings
from prompts.mentor_prompt import get_mentor_prompt
from services.jobs_service import search_jobs
from services.gws_service import GoogleWorkspaceService
from memory.database import (
    save_message, get_history, clear_history, save_tool_result,
    add_learning_item, get_learning_items,
    update_learning_item, complete_learning_item,
    get_overdue_learning_items
)
from services.learning_service import fetch_url_metadata, format_learning_list
from utils.logger import get_logger
from datetime import datetime
import pytz

logger = get_logger("groq_service")

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_current_time",
            "description": (
                "Obtiene la fecha y hora actual en Madrid. "
                "Úsala siempre antes de trabajar con fechas."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []}
        }
    },
    {
        "type": "function",
        "function": {
            "name": "search_jobs",
            "description": (
                "Busca ofertas de empleo de AI Orchestrator, LLM Engineer, "
                "AI Engineer, Augmented Analyst. Úsala cuando el usuario pida "
                "buscar trabajo, ofertas o empleo."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Término de búsqueda. Ejemplos: 'AI Orchestrator', "
                            "'LLM Engineer', 'Data Analyst AI'. "
                            "Si no se especifica usa los roles objetivo por defecto."
                        )
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_emails",
            "description": (
                "Lista emails de Gmail. Úsala para ver correos de "
                "reclutadores, no leídos, etc."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": (
                            "Filtro Gmail. Ejemplos: 'is:unread', "
                            "'from:recruiter'. Default: 'is:unread'"
                        )
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Máximo emails. Default: 10"
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_email_content",
            "description": "Lee el contenido completo de un email por su ID.",
            "parameters": {
                "type": "object",
                "properties": {
                    "message_id": {
                        "type": "string",
                        "description": "ID del email"
                    }
                },
                "required": ["message_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "send_email",
            "description": "Envía email. SOLO usar tras aprobación explícita del usuario.",
            "parameters": {
                "type": "object",
                "properties": {
                    "to": {"type": "string"},
                    "subject": {"type": "string"},
                    "body": {"type": "string"}
                },
                "required": ["to", "subject", "body"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "get_calendar",
            "description": "Ve eventos del calendario de Google.",
            "parameters": {
                "type": "object",
                "properties": {
                    "time_min": {
                        "type": "string",
                        "description": "Fecha inicio ISO 8601. Año siempre 2026."
                    },
                    "time_max": {
                        "type": "string",
                        "description": "Fecha fin ISO 8601."
                    },
                    "max_results": {"type": "integer"}
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_event",
            "description": "Crea evento en calendario. SOLO tras confirmación.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary": {"type": "string"},
                    "start_time": {"type": "string"},
                    "end_time": {"type": "string"},
                    "description": {"type": "string"}
                },
                "required": ["summary", "start_time", "end_time"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_cv",
            "description": (
                "Analiza el CV de Alberto comparándolo con el perfil objetivo. "
                "Úsala cuando Alberto comparta su CV en texto."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "cv_text": {
                        "type": "string",
                        "description": "Texto completo del CV"
                    }
                },
                "required": ["cv_text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_learning_item",
            "description": (
                "Añade un recurso de aprendizaje (video, artículo, curso, "
                "podcast, libro). Úsala cuando Alberto comparta una URL "
                "o mencione algo que quiere aprender. "
                "Primero extrae el título automáticamente de la URL, "
                "luego pregunta relevancia (1-10) y plazo."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": "URL del recurso"
                    },
                    "relevancia": {
                        "type": "integer",
                        "description": "Relevancia del 1 (baja) al 10 (crítica)"
                    },
                    "fecha_objetivo": {
                        "type": "string",
                        "description": "Fecha límite ISO 8601, ej: 2026-04-07"
                    },
                    "notas": {
                        "type": "string",
                        "description": "Notas adicionales opcionales"
                    }
                },
                "required": ["url", "relevancia", "fecha_objetivo"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "list_learning_items",
            "description": (
                "Lista los recursos de aprendizaje pendientes o todos. "
                "Úsala cuando Alberto pregunte por su lista de formación, "
                "recursos pendientes o backlog de aprendizaje."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "estado": {
                        "type": "string",
                        "description": (
                            "Filtrar por estado: 'pendiente', "
                            "'en_progreso' o 'completado'. "
                            "Omitir para ver todos."
                        )
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_learning_item",
            "description": "Actualiza relevancia, fecha o estado de un item.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_id": {"type": "integer"},
                    "relevancia": {"type": "integer"},
                    "fecha_objetivo": {"type": "string"},
                    "estado": {
                        "type": "string",
                        "enum": ["pendiente", "en_progreso", "completado"]
                    },
                    "notas": {"type": "string"}
                },
                "required": ["item_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "complete_learning_item",
            "description": "Marca un recurso de aprendizaje como completado.",
            "parameters": {
                "type": "object",
                "properties": {
                    "item_id": {
                        "type": "integer",
                        "description": "ID del item a completar"
                    }
                },
                "required": ["item_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "read_google_doc",
            "description": (
                "Lee el contenido de un Google Doc o Slides "
                "a partir de su URL o ID. Úsala cuando Alberto "
                "comparta un link de Google Docs."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "url_or_id": {
                        "type": "string",
                        "description": (
                            "URL completa o ID del documento "
                            "de Google Docs/Slides"
                        )
                    }
                },
                "required": ["url_or_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_google_doc",
            "description": (
                "Crea un documento de Google Docs con el título y "
                "contenido indicados. Úsala cuando el usuario pida "
                "crear un documento, nota, informe o cualquier texto "
                "en Google Docs."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "titulo": {
                        "type": "string",
                        "description": "Título del documento"
                    },
                    "contenido": {
                        "type": "string",
                        "description": "Contenido de texto del documento"
                    }
                },
                "required": ["titulo", "contenido"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "create_improved_cv",
            "description": (
                "Genera un CV mejorado en Google Docs con "
                "recomendaciones para el perfil AI Orchestrator. "
                "Úsala después de analizar el CV de Alberto."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "cv_text": {
                        "type": "string",
                        "description": "Texto completo del CV original"
                    },
                    "job_description": {
                        "type": "string",
                        "description": (
                            "Descripción del puesto al que aplica "
                            "(opcional, para adaptar el CV)"
                        )
                    }
                },
                "required": ["cv_text"]
            }
        }
    },
]


class MentorService:
    """Servicio principal del mentor con agent loop y memoria persistente."""

    OPENROUTER_MODELS = [
        "google/gemini-2.0-flash-001",
        "meta-llama/llama-3.3-70b-instruct:free",
        "google/gemma-3-27b-it:free",
        "mistralai/mistral-small-3.1-24b-instruct:free",
        "qwen/qwen3-coder:free",
        "google/gemma-3-12b-it:free",
        "meta-llama/llama-3.2-3b-instruct:free",
    ]

    def __init__(self):
        self.gws = GoogleWorkspaceService()

    def _get_groq_client(self):
        return AsyncOpenAI(
            api_key=settings.groq_api_key,
            base_url="https://api.groq.com/openai/v1"
        )

    def _get_openrouter_client(self):
        return AsyncOpenAI(
            api_key=settings.openrouter_api_key,
            base_url="https://openrouter.ai/api/v1",
            default_headers={
                "HTTP-Referer": "https://github.com/career-mentor-agent",
                "X-Title": "Career Mentor Agent",
            }
        )

    def clear_session(self, user_id: int):
        """Limpia historial en BD al hacer /start."""
        clear_history(user_id)

    async def chat(self, user_id: int, message: str) -> str:
        """Procesa mensaje con agent loop y memoria persistente."""

        # Guardar mensaje del usuario en BD
        save_message(user_id, "user", message)

        # Agent loop con límite de seguridad
        max_iterations = 5
        for iteration in range(max_iterations):
            try:
                # Cargar historial desde SQLite (memoria persistente)
                history = get_history(user_id, limit=20)

                # Construir messages con system prompt fresco
                messages = [
                    {"role": "system", "content": get_mentor_prompt()}
                ] + history

                # Llamar a Groq
                response = await self._call_llm(messages)
                if response is None:
                    return (
                        "No se pudo conectar con ningún servicio de IA. "
                        "Inténtalo en unos minutos."
                    )
                if isinstance(response, str):
                    return response

                # Si el mensaje pide crear CV y no hay tool_calls,
                # forzar reintento con mensaje más explícito
                choice = response.choices[0]
                if (not choice.message.tool_calls and
                        "create_improved_cv" not in str(
                            get_history(user_id, limit=3)
                        ) and
                        any(kw in message.lower() for kw in
                            ["cv", "curriculum", "documento",
                             "google docs", "generar"])):
                    # Añadir hint al historial para el siguiente intento
                    hint = (
                        "INSTRUCCIÓN SISTEMA: El usuario quiere que uses "
                        "la herramienta create_improved_cv ahora mismo. "
                        "No expliques, no preguntes, úsala directamente."
                    )
                    save_message(user_id, "user", hint)
                choice = response.choices[0]

                # Sin tool calls → respuesta final
                if not choice.message.tool_calls:
                    final_response = choice.message.content or ""
                    save_message(user_id, "assistant", final_response)
                    return final_response

                # Con tool calls → ejecutar herramientas
                tool_calls_data = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    }
                    for tc in choice.message.tool_calls
                ]

                # Guardar assistant message con tool calls
                save_message(
                    user_id, "assistant",
                    choice.message.content or "",
                    tool_calls=tool_calls_data
                )

                # Ejecutar cada herramienta
                for tool_call in choice.message.tool_calls:
                    args = json.loads(tool_call.function.arguments or "{}") or {}
                    result = await self._execute_tool(
                        tool_call.function.name, args, user_id
                    )
                    import datetime
                    def _json_serial(obj):
                        if isinstance(obj, (datetime.date, datetime.datetime)):
                            return obj.isoformat()
                        raise TypeError(f"Type {type(obj).__name__} not serializable")
                    result_str = json.dumps(result, ensure_ascii=False, default=_json_serial)

                    # Guardar resultado en BD
                    save_tool_result(user_id, tool_call.id, result_str)

                    logger.info(
                        f"Herramienta {tool_call.function.name} ejecutada"
                    )

            except Exception as e:
                logger.error(
                    f"Error en agent loop iteración {iteration}: {e}",
                    exc_info=True
                )
                return "Lo siento, hubo un error. Inténtalo de nuevo."

        final = "He completado el análisis. ¿En qué más puedo ayudarte?"
        save_message(user_id, "assistant", final)
        return final

    async def _execute_tool(self, name: str, args: Dict,
                            user_id: int) -> Any:
        """Ejecuta una herramienta y devuelve el resultado."""
        try:
            if name == "get_current_time":
                madrid_tz = pytz.timezone('Europe/Madrid')
                now = datetime.now(madrid_tz)
                return {"time": now.strftime("%Y-%m-%d %H:%M:%S %Z")}

            elif name == "search_jobs":
                return await search_jobs(
                    query=args.get("query"),
                    limit=15
                )

            elif name == "get_emails":
                return await self.gws.list_messages(
                    query=args.get("query", "is:unread"),
                    max_results=args.get("max_results", 10)
                )

            elif name == "get_email_content":
                return await self.gws.get_message(args["message_id"])

            elif name == "send_email":
                return await self.gws.send_email(
                    to=args["to"],
                    subject=args["subject"],
                    body=args["body"]
                )

            elif name == "get_calendar":
                return await self.gws.list_events(
                    time_min=args.get("time_min"),
                    time_max=args.get("time_max"),
                    max_results=args.get("max_results", 10)
                )

            elif name == "create_event":
                return await self.gws.create_event(
                    summary=args["summary"],
                    start_time=args["start_time"],
                    end_time=args["end_time"],
                    description=args.get("description", "")
                )

            elif name == "analyze_cv":
                return self._analyze_cv(args.get("cv_text", ""))

            # --- Gestor de Aprendizaje ---

            elif name == "add_learning_item":
                try:
                    url = args.get("url", "")
                    if not url:
                        return {"error": "URL requerida"}
                    
                    # Intentar fetch de metadata con timeout
                    try:
                        from services.learning_service import (
                            fetch_url_metadata
                        )
                        metadata = await fetch_url_metadata(url)
                    except Exception:
                        metadata = {}
                    
                    # Defensivo: garantizar todos los campos
                    titulo = (
                        metadata.get("titulo") or
                        metadata.get("title") or
                        url
                    )
                    descripcion = metadata.get("descripcion", "")
                    tipo = metadata.get("tipo", "video")
                    
                    # Casteo defensivo de relevancia
                    relevancia = args.get("relevancia", 5)
                    if isinstance(relevancia, str):
                        try:
                            relevancia = int(relevancia)
                        except (ValueError, TypeError):
                            relevancia = 5
                    relevancia = max(1, min(10, int(relevancia or 5)))
                    
                    from memory.database import add_learning_item
                    item_id = add_learning_item(
                        user_id=user_id,
                        url=url,
                        titulo=str(titulo)[:200],
                        descripcion=str(descripcion)[:500],
                        tipo=str(tipo),
                        relevancia=relevancia,
                        fecha_objetivo=args.get("fecha_objetivo"),
                        notas=str(args.get("notas", ""))
                    )
                    
                    if item_id and item_id > 0:
                        return {
                            "id": item_id,
                            "titulo": titulo,
                            "tipo": tipo,
                            "relevancia": relevancia,
                            "fecha_objetivo": args.get("fecha_objetivo"),
                            "mensaje": (
                                f"✅ Guardado: '{titulo}' "
                                f"(ID {item_id}). "
                                f"Relevancia {relevancia}/10. "
                                f"Fecha: {args.get('fecha_objetivo')}."
                            )
                        }
                    else:
                        return {"error": "No se pudo guardar en BD"}
                except Exception as e:
                    logger.error(f"Error en add_learning_item: {e}")
                    return {"error": f"Error guardando: {str(e)}"}

            elif name == "list_learning_items":
                from memory.database import get_learning_items
                from services.learning_service import format_learning_list
                try:
                    items = get_learning_items(
                        user_id=user_id,
                        estado=args.get("estado") or "pendiente",
                        limit=20
                    )
                    items = [i for i in (items or []) if i is not None]
                except Exception as e:
                    logger.error(f"Error en list_learning_items: {e}")
                    items = []
                safe_items = [i for i in items if i is not None]
                return {
                    "total": len(safe_items),
                    "items": safe_items,
                    "formatted": format_learning_list(safe_items)
                }

            elif name == "update_learning_item":
                success = update_learning_item(
                    item_id=args["item_id"],
                    user_id=user_id,
                    **{k: v for k, v in args.items() if k != "item_id"}
                )
                return {"success": success, "item_id": args["item_id"]}

            elif name == "complete_learning_item":
                success = complete_learning_item(
                    item_id=args["item_id"]
                )
                return {
                    "success": success,
                    "mensaje": "✅ ¡Recurso completado! Buen trabajo."
                }

            elif name == "create_google_doc":
                try:
                    result = await self.gws.create_document(
                        title=args.get("titulo", "Documento"),
                        text_content=args.get("contenido", "")
                    )
                    if "error" not in result:
                        doc_id = result.get("documentId", "")
                        url = (
                            f"https://docs.google.com/document/d/"
                            f"{doc_id}/edit"
                        )
                        return {
                            "success": True,
                            "url": url,
                            "mensaje": f"✅ Documento creado: {url}"
                        }
                    return result
                except Exception as e:
                    logger.error(f"Error creando doc: {e}")
                    return {"error": str(e)}

            elif name == "read_google_doc":
                from services.cv_service import extract_google_doc_id
                url_or_id = args.get("url_or_id", "")
                doc_id = extract_google_doc_id(url_or_id) or url_or_id
                result = await self.gws.read_document(doc_id)
                return result

            elif name == "create_improved_cv":
                import json as _json
                import os
                profile_path = os.path.join(
                    os.path.dirname(os.path.dirname(__file__)),
                    'data', 'user_profile.json'
                )
                with open(profile_path, 'r', encoding='utf-8') as f:
                    profile = _json.load(f)
                
                cv_text = args.get("cv_text", "")
                job_desc = args.get("job_description", "")
                
                # Reusar analyze_cv para el análisis
                analysis = self._analyze_cv(cv_text)
                
                from services.cv_service import generate_cv_doc_content
                content = generate_cv_doc_content(
                    cv_text, analysis, profile
                )
                
                # Añadir descripción del puesto si se proporcionó
                if job_desc:
                    content += (
                        f"\n\nADAPTACIÓN AL PUESTO\n"
                        f"────────────────────\n{job_desc[:500]}"
                    )
                
                title = "CV Mejorado — Alberto Valle — AI Orchestrator"
                result = await self.gws.create_cv_document(title, content)
                
                if "error" not in result:
                    doc_url = result.get(
                        "url",
                        f"https://docs.google.com/document/d/"
                        f"{result.get('documentId', '')}/edit"
                    )
                    return {
                        "success": True,
                        "url": doc_url,
                        "mensaje": (
                            f"✅ CV mejorado creado en Google Docs:\n"
                            f"{doc_url}\n\n"
                            f"Match con perfil objetivo: "
                            f"{analysis['porcentaje_match_objetivo']}%"
                        )
                    }
                return result

            else:
                return {"error": f"Herramienta {name} no encontrada"}

        except Exception as e:
            logger.error(f"Error ejecutando {name}: {e}")
            return {"error": str(e)}

    def _analyze_cv(self, cv_text: str) -> Dict:
        """Analiza CV comparándolo con perfil objetivo."""
        TARGET_SKILLS = [
            "llm", "rag", "langchain", "python", "prompt engineering",
            "ai agents", "vector database", "mlops", "openai", "huggingface",
            "langgraph", "autogen", "crewai", "fastapi", "docker",
            "langsmith", "embeddings", "fine-tuning", "retrieval"
        ]

        cv_lower = cv_text.lower()
        encontradas = [s for s in TARGET_SKILLS if s in cv_lower]
        faltantes = [s for s in TARGET_SKILLS if s not in cv_lower]
        match_pct = int(len(encontradas) / len(TARGET_SKILLS) * 100)

        return {
            "skills_detectadas": encontradas,
            "skills_faltantes": faltantes[:8],
            "porcentaje_match_objetivo": match_pct,
            "resumen": (
                f"Tu CV tiene {match_pct}% de match con el perfil objetivo. "
                f"Skills detectadas: {', '.join(encontradas) or 'ninguna de las objetivo'}. "
                f"Skills prioritarias a desarrollar: {', '.join(faltantes[:5])}."
            ),
            "cv_texto": cv_text[:3000]
        }

    async def _call_llm(self, messages: List[Dict[str, Any]]) -> Any:
        """
        Cadena de fallbacks:
        Groq 70B → Groq 8B (prompt reducido) → OpenRouter (7 modelos)
        """
        # 1. Groq 70B — Principal
        if settings.groq_api_key:
            client = self._get_groq_client()
            try:
                response = await client.chat.completions.create(
                    model=settings.groq_model,
                    messages=messages,
                    tools=TOOLS,
                    tool_choice="auto",
                    max_tokens=2000,
                    temperature=0.7
                )
                logger.info("Groq 70B respondió correctamente")
                return response
            except Exception as e:
                error_str = str(e).lower()
                if any(x in error_str for x in
                       ["rate_limit", "429", "413", "tokens"]):
                    logger.warning(
                        "Groq 70B límite superado. Intentando Groq 8B..."
                    )
                    try:
                        from prompts.mentor_prompt import MENTOR_TINY_PROMPT
                        # Truncar historial para respetar límite 6000 TPM de 8B
                        recent = (
                            messages[-3:] if len(messages) > 3 else messages
                        )
                        non_system_recent = [
                            m for m in recent if m.get("role") != "system"
                        ]
                        fallback_messages = [
                            {"role": "system", "content": MENTOR_TINY_PROMPT}
                        ] + non_system_recent
                        response = await client.chat.completions.create(
                            model=settings.groq_model_fallback,
                            messages=fallback_messages,
                            tools=TOOLS,
                            tool_choice="auto",
                            max_tokens=800,
                            temperature=0.7
                        )
                        logger.info("Groq 8B respondió correctamente")
                        return response
                    except Exception as e2:
                        logger.warning(f"Groq 8B también falló: {e2}")
                else:
                    logger.error(f"Error Groq 70B (no rate limit): {e}")

        # 2. OpenRouter — 7 modelos en orden
        if settings.openrouter_api_key:
            logger.info("Intentando fallback a OpenRouter...")
            return await self._call_openrouter(messages)

        logger.error("Todos los servicios han fallado.")
        return None

    async def _call_openrouter(
        self, messages: List[Dict[str, Any]]
    ) -> Any:
        """Prueba 7 modelos gratuitos de OpenRouter en orden."""
        clean_messages = []
        for m in messages:
            role = m["role"]
            content = m.get("content", "")
            if role == "system":
                clean_messages.append({
                    "role": "user",
                    "content": f"[Instrucciones]: {content}"
                })
            elif role == "tool":
                clean_messages.append({
                    "role": "user",
                    "content": f"[Resultado herramienta]: {content}"
                })
            elif m.get("tool_calls"):
                tc_text = ", ".join(
                    f"{tc['function']['name']}"
                    for tc in m.get("tool_calls", [])
                )
                clean_messages.append({
                    "role": "assistant",
                    "content": f"[Herramientas usadas: {tc_text}]"
                })
            else:
                clean_messages.append({"role": role, "content": content})

        client = self._get_openrouter_client()
        models_to_try = [settings.openrouter_model]
        for m in self.OPENROUTER_MODELS:
            if m not in models_to_try:
                models_to_try.append(m)

        for model in models_to_try:
            try:
                response = await client.chat.completions.create(
                    model=model,
                    messages=clean_messages,
                    max_tokens=1024,
                    temperature=0.7
                )
                logger.info(f"OpenRouter ({model}) respondió correctamente")
                return response
            except Exception as e:
                logger.warning(
                    f"OpenRouter ({model}) falló: {e}. "
                    "Probando siguiente..."
                )
                continue

        logger.error("Todos los modelos de OpenRouter han fallado.")
        return None


# Instancia global
mentor_service = MentorService()
