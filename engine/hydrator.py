"""
Engine: hydrator.py
Description: Hidratador dinámico (Pico-Ansible Hydrator) — motor de plantillas compartido.

Hidrata plantillas en DOS modos:
  - TEXTO: plantillas Go (`tpl_*.go`) con marcadores `{{PARAM}}` -> código fuente.
  - ESTRUCTURAL: dict/list (playbooks) con marcadores `${var}` -> estructura concreta.

RE-as-SDD sobre Jinja2 (se extraen sus PATRONES, no la librería — JinjaX/componentes HTML y el
templating de texto sobre JSON se rechazan por incompatibles/frágiles):
  - StrictUndefined  -> un parámetro requerido ausente FALLA (no se sustituye en silencio).
  - filtro `default` -> el contrato declara defaults por parámetro.
  - tipado/coerción  -> cada parámetro se coacciona a su tipo declarado (alinea con CUE).
  - SandboxedEnvironment -> sustitución pura de datos, CERO eval de expresiones (sin RCE).
  - autoescaping -> inserción tipada en la estructura, nunca splicing de strings.
"""

import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

# Marcadores: {{WORD}} para texto Go; ${word} para estructura (playbooks). Distintos a
# propósito para no colisionar con las plantillas text/template nativas de Go ({{.Field}}).
_TEXT_PLACEHOLDER = re.compile(r"\{\{(\w+)\}\}")
_STRUCT_WHOLE = re.compile(r"^\$\{(\w+)\}$")
_STRUCT_EMBED = re.compile(r"\$\{(\w+)\}")


def _coerce(value: Any, typ: Optional[str]) -> Any:
    """Coerción de un valor a su tipo declarado (análogo al tipado de filtros Jinja)."""
    if typ in (None, "", "string", "str", "any"):
        return value
    try:
        if typ in ("int", "integer"):
            return int(value)
        if typ in ("float", "number"):
            return float(value)
        if typ in ("bool", "boolean"):
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() in ("1", "true", "yes", "on")
        if typ in ("list", "array"):
            return value if isinstance(value, list) else [value]
    except (ValueError, TypeError) as e:
        raise ValueError(f"no se pudo coaccionar '{value}' a {typ}: {e}")
    return value


def resolve_params(contract: Optional[List[Dict[str, Any]]],
                   provided: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Resuelve parámetros contra un contrato: aplica defaults, exige requeridos
    (StrictUndefined) y coacciona tipos. Devuelve el dict resuelto.

    contract: [{name, type?, required?=True, default?}]. provided: valores del agente.
    """
    contract = contract or []
    provided = provided or {}
    out: Dict[str, Any] = {}
    declared = set()
    for spec in contract:
        name = spec.get("name")
        if not name:
            continue
        declared.add(name)
        typ = spec.get("type")
        if name in provided:
            out[name] = _coerce(provided[name], typ)
        elif "default" in spec:
            out[name] = _coerce(spec["default"], typ)
        elif spec.get("required", True):
            raise ValueError(f"parámetro requerido ausente: '{name}'")
        # opcional sin default -> se omite
    for k, v in provided.items():   # pass-through de vars no declaradas
        if k not in declared:
            out[k] = v
    return out


def hydrate_struct(obj: Any, variables: Dict[str, Any], strict: bool = True) -> Any:
    """Sustitución ESTRUCTURAL de `${var}` en los valores string de un dict/list.
    Si el valor es exactamente '${x}', se reemplaza por el valor TIPADO (no string);
    si está embebido ('a-${x}-b'), se interpola como texto. Sin eval — solo datos."""
    def sub_str(s: str) -> Any:
        whole = _STRUCT_WHOLE.match(s)
        if whole:
            name = whole.group(1)
            if name in variables:
                return variables[name]          # preserva el tipo real
            if strict:
                raise ValueError(f"variable sin valor: ${{{name}}}")
            return s

        def repl(mo: "re.Match") -> str:
            name = mo.group(1)
            if name in variables:
                return str(variables[name])
            if strict:
                raise ValueError(f"variable sin valor: ${{{name}}}")
            return mo.group(0)
        return _STRUCT_EMBED.sub(repl, s)

    if isinstance(obj, dict):
        return {k: hydrate_struct(v, variables, strict) for k, v in obj.items()}
    if isinstance(obj, list):
        return [hydrate_struct(x, variables, strict) for x in obj]
    if isinstance(obj, str):
        return sub_str(obj)
    return obj


class TemplateHydrator:
    def __init__(self, templates_dir: Optional[Path] = None):
        self.templates_dir = templates_dir or (
            Path(__file__).resolve().parent.parent / "templates"
        )

    def list_available_templates(self) -> list[str]:
        if not self.templates_dir.exists():
            return []
        return [f.name for f in self.templates_dir.glob("tpl_*.go")]

    def hydrate(self, template_name: str, params: Dict[str, Any],
                contract: Optional[List[Dict[str, Any]]] = None, strict: bool = False) -> str:
        """Hidrata una plantilla Go (modo TEXTO). Con `contract`, aplica resolve_params
        (defaults + requeridos + tipos). Con `strict=True`, falla si queda algún `{{PARAM}}`
        sin resolver (StrictUndefined); default False por compatibilidad con plantillas Go
        que usen `{{ .Field }}` nativas."""
        candidates = [
            self.templates_dir / template_name,
            self.templates_dir / f"tpl_{template_name}.go",
            self.templates_dir / f"tpl_{template_name.replace('-', '_')}.go",
            self.templates_dir / template_name.replace("-", "_"),
        ]
        template_file = None
        for cand in candidates:
            if cand.exists():
                template_file = cand
                break
        if not template_file:
            raise FileNotFoundError(
                f"Plantilla no encontrada: {template_name} en {self.templates_dir}"
            )

        content = template_file.read_text(encoding="utf-8")
        resolved = resolve_params(contract, params) if contract else params

        for key, value in resolved.items():
            placeholder = f"{{{{{key}}}}}"
            if isinstance(value, bool):
                val_str = "true" if value else "false"
            elif isinstance(value, (int, float)):
                val_str = str(value)
            elif isinstance(value, str):
                val_str = f'"{value}"' if not (value.startswith('"') and value.endswith('"')) else value
            else:
                val_str = json.dumps(value)
            content = content.replace(placeholder, val_str)

        if strict:
            leftover = sorted(set(_TEXT_PLACEHOLDER.findall(content)))
            if leftover:
                raise ValueError(f"placeholders sin resolver (StrictUndefined): {leftover}")
        return content
