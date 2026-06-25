import os
import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional, Dict
from dotenv import load_dotenv
from lightfield import Lightfield

# 1. Configuración de variables de entorno y cliente
load_dotenv()
API_KEY = os.getenv("LIGHTFIELD_API_KEY")

if not API_KEY:
    raise ValueError("No se encontró LIGHTFIELD_API_KEY en el archivo .env")

client = Lightfield(api_key=API_KEY)

# 2. Inicialización de la API
app = FastAPI(
    title="Lightfield Middleware API",
    description="API para automatizar Cuentas, Contactos y Oportunidades",
    version="2.3"   # <-- cámbialo
)

# --- TRADUCTOR DE CAMPOS SINGLE_SELECT ---
# Lightfield exige el código opt_ para los campos de selección, no el texto.
# Generalizamos: una sola función lee las opciones de $stage, tier e initiative.

SELECT_FIELDS = ["$stage", "tier", "initiative"]  # campos a traducir

# Fallbacks estáticos con los IDs reales (por si definitions() falla al arrancar).
SELECT_MAP_FALLBACK: Dict[str, Dict[str, str]] = {
    "$stage": {
        "Nurturing": "opt_63761c15-a514-489d-a0e9-ebb097446094",
        "Lead": "opt_62d3f3db-1ea8-4c9c-a59b-14d4c5d9fef9",
        "Qualified Lead": "opt_7f0eca42-846d-47ee-9690-2d9f7de4f691",
        "Solution Fit": "opt_0be7baba-e192-4dda-a0a1-fc12d69d69c9",
        "Negotiating": "opt_b13c9790-565e-43c0-b08e-10c41a10b225",
        "Won": "opt_611b08b2-2744-4fbf-8ace-ed48e63722b2",
        "Lost": "opt_887c503c-b78a-4200-a63c-1d8eb6e9445e",
        "Onboarding": "opt_45c5dea8-9918-4a1d-9557-fde3ef94c12a",
        "Stable": "opt_6f158d7d-65dc-4069-97d8-75a241f0bffc",
        "Struggling": "opt_9593f6c9-5600-425e-9bc1-e13d9d1ebf2c",
        "Expanding": "opt_1950588e-d581-4fb5-8286-787e1f32c1a0",
        "Churn": "opt_acbe1211-bd79-46bc-930e-609a58a0f21c",
    },
    "tier": {
        "Cardumen": "opt_813068f8-b97c-426d-94e2-554fe91f61df",
        "Tiburon": "opt_9d6c4a4f-6154-4f62-a6b2-f52b6b4e7ceb",
        "Ballena": "opt_96ad42c9-66c4-446c-94cc-e5b50ef57235",
    },
    "initiative": {
        "Catalogueras": "opt_15f587bf-ef01-4705-a503-a621c12fc1d9",
        "Cardumen": "opt_02d87879-815c-4ce5-b7cd-19abec319abe",
    },
}

DEFAULT_STAGE = "Lead"  # se usa si Platica manda el stage vacío


def _norm(s: str) -> str:
    """Normaliza: quita espacios y baja a minúsculas. 'Qualified Lead' == 'qualifiedlead'."""
    return "".join((s or "").lower().split())


def load_select_maps() -> Dict[str, Dict[str, str]]:
    """
    Lee las opciones reales de los campos SINGLE_SELECT desde Lightfield al arrancar.
    Devuelve {nombre_campo: {label: opt_id}}. Usa el fallback si algo falla.
    """
    try:
        defs = client.opportunity.definitions()
        data = defs.model_dump()
        field_defs = data.get("field_definitions", {})

        maps: Dict[str, Dict[str, str]] = {}
        for field in SELECT_FIELDS:
            options = (
                field_defs.get(field, {})
                .get("type_configuration", {})
                .get("options", [])
            )
            mapping = {opt["label"]: opt["id"] for opt in options if opt.get("label") and opt.get("id")}
            if mapping:
                maps[field] = mapping
                print(f"[SELECT_MAP] {field}: {len(mapping)} opciones -> {list(mapping.keys())}")
            else:
                maps[field] = dict(SELECT_MAP_FALLBACK.get(field, {}))
                print(f"[SELECT_MAP] {field}: sin opciones en definitions(), usando fallback.")
        return maps
    except Exception as e:
        print(f"[SELECT_MAP] Error leyendo definitions() ({e!r}); usando fallbacks estáticos.")
        return {k: dict(v) for k, v in SELECT_MAP_FALLBACK.items()}


# Se carga una sola vez al arrancar el módulo
SELECT_MAPS: Dict[str, Dict[str, str]] = load_select_maps()
# Versión normalizada para búsqueda tolerante a espacios/mayúsculas
SELECT_MAPS_NORM: Dict[str, Dict[str, str]] = {
    field: {_norm(k): v for k, v in mapping.items()}
    for field, mapping in SELECT_MAPS.items()
}


def resolve_option_id(field: str, text: Optional[str], required: bool = True,
                       default: Optional[str] = None) -> Optional[str]:
    """
    Traduce el texto de una opción a su código opt_ para un campo dado.
    - required=True: lanza 400 si el texto no es válido.
    - required=False: si el texto viene vacío, devuelve None (campo omitido).
    """
    clean = (text or "").strip()
    if not clean:
        if default:
            clean = default
        elif required:
            raise HTTPException(status_code=400, detail=f"El campo '{field}' es obligatorio.")
        else:
            return None

    opt_id = SELECT_MAPS_NORM.get(field, {}).get(_norm(clean))
    if not opt_id:
        validas = list(SELECT_MAPS.get(field, {}).keys())
        raise HTTPException(
            status_code=400,
            detail=f"Valor '{clean}' no es válido para '{field}'. Válidos: {validas}"
        )
    return opt_id


# --- MODELOS DE DATOS ---

class AccountRequest(BaseModel):
    name: str
    website: str
    linkedin: str
    revenue_range: Optional[str] = None
    headcount: Optional[str] = None
    account_type: Optional[str] = None
    industry: Optional[List[str]] = ["Tecnología", "SaaS"]

class ContactCreateRequest(BaseModel):
    first_name: str
    last_name: str
    email: str
    phone: Optional[str] = None
    account_id: str

class OpportunityByNameRequest(BaseModel):
    account_name: str
    opportunity_name: str
    next_step: str = "Revisar viabilidad técnica"
    stage: str = "Lead"
    tier: str          # obligatorio: Cardumen, Tiburon, Ballena
    initiative: str    # obligatorio: Catalogueras, Cardumen

class OpportunityUpdateByNameRequest(BaseModel):
    opportunity_name: str
    stage: str
    next_step: str
    tier: str
    initiative: str

class NoteCreateSmartRequest(BaseModel):
    title: str
    content: Optional[str] = None
    account_name: Optional[str] = Field(default=None, description="Nombre de la cuenta a buscar")
    opportunity_name: Optional[str] = Field(default=None, description="Nombre de la oportunidad a buscar")

# --- FUNCIONES AUXILIARES (Helpers) ---

def get_account_id_by_name(name: str) -> Optional[str]:
    offset = 0
    while True:
        accounts = client.account.list(limit=25, offset=offset)
        if not accounts.data:
            break
        for account in accounts.data:
            name_field = account.fields.get('$name')
            if name_field and hasattr(name_field, "value") and name_field.value == name:
                return account.id
        offset += 25
    return None

def get_opportunity_id_by_name(name: str) -> Optional[str]:
    offset = 0
    while True:
        opportunities = client.opportunity.list(limit=25, offset=offset)
        if not opportunities.data:
            break
        for opportunity in opportunities.data:
            name_field = opportunity.fields.get('$name')
            if name_field and hasattr(name_field, "value") and name_field.value == name:
                return opportunity.id
        offset += 25
    return None

# --- ENDPOINTS ---

@app.get("/select-options", summary="Listar opciones válidas de stage/tier/initiative (debug)")
def api_list_select_options():
    return {"success": True, "fields": SELECT_MAPS}

@app.post("/notes", summary="Crear una Nota Inteligente (por nombres)")
def api_create_note_smart(payload: NoteCreateSmartRequest):
    note_relationships = {}

    if payload.account_name:
        acc_id = get_account_id_by_name(payload.account_name)
        if not acc_id:
            raise HTTPException(status_code=404, detail=f"Cuenta '{payload.account_name}' no encontrada.")
        note_relationships["$account"] = [acc_id]

    if payload.opportunity_name:
        opp_id = get_opportunity_id_by_name(payload.opportunity_name)
        if not opp_id:
            raise HTTPException(status_code=404, detail=f"Oportunidad '{payload.opportunity_name}' no encontrada.")
        note_relationships["$opportunity"] = [opp_id]

    try:
        note_fields = {"$title": payload.title}
        if payload.content:
            note_fields["$content"] = payload.content

        request_body = {"fields": note_fields}
        if note_relationships:
            request_body["relationships"] = note_relationships

        url = "https://api.lightfield.app/v1/notes"
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Lightfield-Version": "2026-03-01",
            "Content-Type": "application/json"
        }

        response = requests.post(url, headers=headers, json=request_body)

        if response.status_code not in (200, 201):
            error_details = response.text
            try:
                error_details = response.json()
            except:
                pass
            raise HTTPException(status_code=response.status_code, detail=f"Error de Lightfield: {error_details}")

        data = response.json()

        return {
            "success": True,
            "note_id": data.get("id"),
            "linked_to": {
                "account": payload.account_name if payload.account_name else "Ninguna",
                "opportunity": payload.opportunity_name if payload.opportunity_name else "Ninguna"
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/accounts", summary="Crear una nueva Cuenta")
def api_create_account(payload: AccountRequest):
    try:
        account_fields = {
            "$name": payload.name,
        }
        if payload.website: account_fields["$website"] = [payload.website]
        if payload.linkedin: account_fields["$linkedIn"] = payload.linkedin
        if payload.industry: account_fields["$industry"] = payload.industry
        if payload.revenue_range: account_fields["$revenueRange"] = payload.revenue_range
        if payload.headcount: account_fields["$headcount"] = payload.headcount
        if payload.account_type: account_fields["type"] = [payload.account_type]

        response = client.account.create(fields=account_fields)
        return {"success": True, "account_id": response.id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/accounts/names", summary="Listar nombres e IDs de todas las cuentas")
def api_list_account_names():
    accounts = []
    offset = 0
    while True:
        page = client.account.list(limit=25, offset=offset)
        if not page.data:
            break
        for account in page.data:
            name_field = account.fields.get("$name")
            if name_field and name_field.value:
                accounts.append({
                    "name": name_field.value,
                    "id": account.id
                })
        offset += 25
    accounts.sort(key=lambda x: x["name"])
    return {"success": True, "total": len(accounts), "accounts": accounts}

@app.post("/contacts", summary="Crear un nuevo Contacto")
def api_create_contact(payload: ContactCreateRequest):
    try:
        contact_fields = {
            "$name": {"firstName": payload.first_name, "lastName": payload.last_name},
            "$email": [payload.email]
        }
        if payload.phone:
            contact_fields["$phone"] = [payload.phone]

        response = client.contact.create(
            fields=contact_fields,
            relationships={"$account": [payload.account_id]}
        )
        return {"success": True, "contact_id": response.id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/contacts/names", summary="Listar nombres e IDs de todos los contactos")
def api_list_contact_names():
    contacts = []
    offset = 0

    while True:
        page = client.contact.list(limit=25, offset=offset)
        if not page.data:
            break

        for contact in page.data:
            name_field = contact.fields.get("$name")
            if not name_field or name_field.value is None:
                continue

            nv = name_field.value

            # Normalizamos a dict sin importar cómo lo envuelva el SDK:
            # - objeto Pydantic (FullName) -> model_dump()
            # - dict crudo -> tal cual
            if hasattr(nv, "model_dump"):
                nv = nv.model_dump()

            if isinstance(nv, dict):
                # Cubrimos camelCase y snake_case por si acaso
                first = nv.get("firstName") or nv.get("first_name") or ""
                last = nv.get("lastName") or nv.get("last_name") or ""
            else:
                first = (getattr(nv, "firstName", None)
                         or getattr(nv, "first_name", None) or "")
                last = (getattr(nv, "lastName", None)
                        or getattr(nv, "last_name", None) or "")

            full_name = f"{first} {last}".strip()
            if not full_name:
                continue

            acc_rel = contact.relationships.get("$account")
            account_id = acc_rel.values[0] if acc_rel and acc_rel.values else None

            contacts.append({
                "name": full_name,
                "id": contact.id,
                "account_id": account_id
            })

        offset += 25

    contacts.sort(key=lambda x: x["name"])
    return {"success": True, "total": len(contacts), "contacts": contacts}


@app.post("/opportunities/by-account-name", summary="Crear Oportunidad buscando cuenta por nombre")
def api_create_opportunity_smart(payload: OpportunityByNameRequest):
    account_id = get_account_id_by_name(payload.account_name)
    if not account_id:
        raise HTTPException(status_code=404, detail=f"La cuenta '{payload.account_name}' no existe.")

    # Stage es obligatorio; tier e initiative también lo son (400 si vienen vacíos)
    stage_id = resolve_option_id("$stage", payload.stage, required=True, default=DEFAULT_STAGE)

    fields = {
        "$name": payload.opportunity_name,
        "$stage": stage_id,
        "$nextStep": payload.next_step,
        "tier": resolve_option_id("tier", payload.tier, required=True),
        "initiative": resolve_option_id("initiative", payload.initiative, required=True),
    }

    try:
        response = client.opportunity.create(
            fields=fields,
            relationships={"$account": account_id}
        )
        return {"success": True, "opportunity_id": response.id, "linked_to_account_id": account_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=repr(e))

@app.patch("/opportunities/update-by-name", summary="Actualizar Oportunidad buscando por nombre")
def api_update_opportunity_by_name(payload: OpportunityUpdateByNameRequest):
    opportunity_id = get_opportunity_id_by_name(payload.opportunity_name)

    if not opportunity_id:
        raise HTTPException(status_code=404, detail=f"Oportunidad '{payload.opportunity_name}' no encontrada.")

    stage_id = resolve_option_id("$stage", payload.stage, required=True, default=DEFAULT_STAGE)

    fields = {
        "$stage": stage_id,
        "$nextStep": payload.next_step,
        "tier": resolve_option_id("tier", payload.tier, required=True),
        "initiative": resolve_option_id("initiative", payload.initiative, required=True),
    }

    try:
        response = client.opportunity.update(
            id=opportunity_id,
            fields=fields,
        )
        return {"success": True, "message": "Oportunidad actualizada", "opportunity_id": response.id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=repr(e))

@app.get("/debug/whoami", summary="Verificar identidad/key en este entorno")
def api_debug_whoami():
    key = os.getenv("LIGHTFIELD_API_KEY") or ""
    info = {
        "key_present": bool(key),
        "key_length": len(key),
        "key_preview": (key[:6] + "..." + key[-4:]) if len(key) > 12 else "TOO_SHORT",
    }
    # Cuenta cuántos contactos ve esta key, leyendo totalCount directo
    try:
        page = client.contact.list(limit=25, offset=0)
        info["contacts_total_count"] = getattr(page, "total_count", None) or getattr(page, "totalCount", None)
        info["first_page_len"] = len(page.data) if page.data else 0
    except Exception as e:
        info["error"] = repr(e)
    return info

@app.get("/debug/contact-raw", summary="Ver estructura cruda de un contacto vía HTTP directo")
def api_debug_contact_raw():
    url = "https://api.lightfield.app/v1/contacts?limit=1&offset=0"
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Lightfield-Version": "2026-03-01",
        "Content-Type": "application/json",
    }
    r = requests.get(url, headers=headers)
    return {
        "status": r.status_code,
        "version_marker": "contact-raw-v1",  # para confirmar que corre ESटE código
        "body": r.json() if r.status_code == 200 else r.text,
    }
