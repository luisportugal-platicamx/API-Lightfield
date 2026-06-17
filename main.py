import os
import requests  # <-- Añadido exclusivamente para que funcione Notes
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from typing import List, Optional
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
    version="1.4.0"
)

# --- MODELOS DE DATOS ---

class AccountRequest(BaseModel):
    name: str
    website: str
    linkedin: str
    revenue_range: str = Field(default="Less than $1M")
    headcount: str = Field(default="1-10")
    account_type: str = Field(default="Customer")
    industry: Optional[List[str]] = ["Tecnología", "SaaS"]

class ContactCreateRequest(BaseModel):
    first_name: str
    last_name: str
    email: str
    phone: Optional[str] = None
    account_id: str

class OpportunityCreateRequest(BaseModel):
    account_id: str
    name: str
    next_step: str = "Revisar viabilidad técnica"
    stage: str = "Lead"

class OpportunityByNameRequest(BaseModel):
    account_name: str
    opportunity_name: str
    next_step: str = "Revisar viabilidad técnica"
    stage: str = "Lead"

class OpportunityUpdateRequest(BaseModel):
    stage: str
    next_step: str

class OpportunityUpdateByNameRequest(BaseModel):
    opportunity_name: str
    stage: str
    next_step: str

class NoteCreateSmartRequest(BaseModel):
    title: str
    content: Optional[str] = None
    account_name: Optional[str] = Field(default=None, description="Nombre de la cuenta a buscar")
    opportunity_name: Optional[str] = Field(default=None, description="Nombre de la oportunidad a buscar")

# --- FUNCIONES AUXILIARES (Helpers) ---

def get_account_id_by_name(name: str) -> Optional[str]:
    """Busca el ID de una cuenta por su nombre."""
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
    """Busca el ID de una oportunidad por su nombre."""
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

@app.post("/notes", summary="Crear una Nota Inteligente (por nombres)")
def api_create_note_smart(payload: NoteCreateSmartRequest):
    """
    Busca automáticamente los IDs de Cuenta y Oportunidad basándose en los nombres.
    Al no existir client.note en el SDK, usamos peticiones HTTP directas.
    """
    note_relationships = {}

    # 1. Si se proporciona nombre de cuenta, buscamos su ID
    if payload.account_name:
        acc_id = get_account_id_by_name(payload.account_name)
        if not acc_id:
            raise HTTPException(status_code=404, detail=f"Cuenta '{payload.account_name}' no encontrada.")
        note_relationships["$account"] = [acc_id]

    # 2. Si se proporciona nombre de oportunidad, buscamos su ID
    if payload.opportunity_name:
        opp_id = get_opportunity_id_by_name(payload.opportunity_name)
        if not opp_id:
            raise HTTPException(status_code=404, detail=f"Oportunidad '{payload.opportunity_name}' no encontrada.")
        note_relationships["$opportunity"] = [opp_id]

    try:
        # 3. Construimos los campos de la nota
        note_fields = {"$title": payload.title}
        if payload.content:
            note_fields["$content"] = payload.content

        request_body = {
            "fields": note_fields
        }
        if note_relationships:
            request_body["relationships"] = note_relationships

        # 4. Petición HTTP directa por detrás (Bypass del SDK)
        url = "https://api.lightfield.app/v1/notes"
        headers = {
            "Authorization": f"Bearer {API_KEY}",
            "Lightfield-Version": "2026-03-01",
            "Content-Type": "application/json"
        }

        response = requests.post(url, headers=headers, json=request_body)
        
        # Validación estricta de la respuesta
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
        raise # Dejar pasar los 404 y los errores de validación de Lightfield
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/accounts", summary="Crear una nueva Cuenta")
def api_create_account(payload: AccountRequest):
    try:
        response = client.account.create(
            fields={
                "$name": payload.name,  
                "$website": [payload.website], 
                "$linkedIn": payload.linkedin,           
                "$industry": payload.industry,  
                "$revenueRange": payload.revenue_range,        
                "$headcount": payload.headcount,            
                "type": [payload.account_type], 
            }
        )
        return {"success": True, "account_id": response.id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/accounts/names", summary="Listar nombres de todas las cuentas")
def api_list_account_names():
    names = []
    offset = 0
    while True:
        page = client.account.list(limit=25, offset=offset)
        if not page.data:
            break
        for account in page.data:
            name_field = account.fields.get("$name")
            if name_field and name_field.value:
                names.append(name_field.value)
        offset += 25
        if offset >= page.total_count:
            break
    return {"success": True, "total": len(names), "names": sorted(names)}


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

@app.post("/opportunities/by-account-name", summary="Crear Oportunidad buscando cuenta por nombre")
def api_create_opportunity_smart(payload: OpportunityByNameRequest):
    account_id = get_account_id_by_name(payload.account_name)
    if not account_id:
        raise HTTPException(status_code=404, detail=f"La cuenta '{payload.account_name}' no existe.")
    
    try:
        response = client.opportunity.create(
            fields={
                "$name": payload.opportunity_name, 
                "$stage": payload.stage,                
                "$nextStep": payload.next_step,
            },
            relationships={"$account": account_id}
        )
        return {"success": True, "opportunity_id": response.id, "linked_to_account_id": account_id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.patch("/opportunities/update-by-name", summary="Actualizar Oportunidad buscando por nombre")
def api_update_opportunity_by_name(payload: OpportunityUpdateByNameRequest):
    """
    Busca automáticamente el ID de la oportunidad por nombre y luego aplica el update.
    """
    opportunity_id = get_opportunity_id_by_name(payload.opportunity_name)
    
    if not opportunity_id:
        raise HTTPException(status_code=404, detail=f"Oportunidad '{payload.opportunity_name}' no encontrada.")
    
    try:
        response = client.opportunity.update(
            id=opportunity_id,  
            fields={
                "$stage": payload.stage,       
                "$nextStep": payload.next_step  
            },
        )
        return {"success": True, "message": "Oportunidad actualizada", "opportunity_id": response.id}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
