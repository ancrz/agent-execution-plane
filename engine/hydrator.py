"""
Engine: hydrator.py
Description: Hidratador dinámico de plantillas atómicas en Go (Pico-Ansible Hydrator).
Inyecta parámetros validados por CUE/Pydantic en plantillas Go (tpl_*.go) para generar
código fuente final listo para compilación estática y ejecución en memoria.
"""

from pathlib import Path
from typing import Any, Dict, Optional


class TemplateHydrator:
    def __init__(self, templates_dir: Optional[Path] = None):
        self.templates_dir = templates_dir or (
            Path(__file__).resolve().parent.parent / "templates"
        )

    def list_available_templates(self) -> list[str]:
        if not self.templates_dir.exists():
            return []
        return [f.name for f in self.templates_dir.glob("tpl_*.go")]

    def hydrate(self, template_name: str, params: Dict[str, Any]) -> str:
        """
        Lee una plantilla Go y sustituye marcadores de posición {{PARAM_NAME}}
        por los valores concretos proporcionados.
        """
        template_file = self.templates_dir / template_name
        if not template_file.exists():
            # Intentar añadiendo prefijo si no lo tiene
            alt_file = self.templates_dir / f"tpl_{template_name}.go"
            if alt_file.exists():
                template_file = alt_file
            else:
                raise FileNotFoundError(
                    f"Plantilla no encontrada: {template_name} en {self.templates_dir}"
                )

        content = template_file.read_text(encoding="utf-8")

        # Reemplazo seguro de parámetros declarados
        for key, value in params.items():
            placeholder = f"{{{{{key}}}}}"
            if isinstance(value, bool):
                val_str = "true" if value else "false"
            elif isinstance(value, (int, float)):
                val_str = str(value)
            elif isinstance(value, str):
                val_str = f'"{value}"' if not (value.startswith('"') and value.endswith('"')) else value
            else:
                import json
                val_str = json.dumps(value)
            content = content.replace(placeholder, val_str)

        return content
