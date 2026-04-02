import re
from typing import Optional

def normalize_url(url: str) -> str:
    """
    Normaliza URLs para evitar duplicados en la base de datos.
    - Convierte youtu.be a youtube.com
    - Elimina parámetros de tracking (?utm, ?si, etc.)
    - Elimina 'www.' y trailing slashes
    """
    if not url:
        return ""
    
    url = url.strip().lower()
    
    # Manejar YouTube shorts/shorteners
    # youtu.be/ID -> youtube.com/watch?v=ID
    youtube_short = re.search(r"youtu\.be/([a-zA-Z0-9_-]+)", url)
    if youtube_short:
        video_id = youtube_short.group(1)
        url = f"https://youtube.com/watch?v={video_id}"
    
    # Eliminar parámetros de tracking (mantener 'v' para youtube)
    if "?" in url:
        base, params = url.split("?", 1)
        # Solo mantener el parámetro 'v' si es youtube
        if "youtube.com" in base and "v=" in params:
            v_match = re.search(r"v=([a-zA-Z0-9_-]+)", params)
            if v_match:
                url = f"{base}?v={v_match.group(1)}"
            else:
                url = base
        else:
            url = base
            
    # Limpieza final
    url = url.replace("https://", "").replace("http://", "")
    url = url.replace("www.", "")
    url = url.rstrip("/")
    
    return url
