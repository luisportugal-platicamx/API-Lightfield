# Usar una imagen oficial de Python ligera para reducir el tamaño final
FROM python:3.11-slim

# Establecer el directorio de trabajo dentro del contenedor
WORKDIR /app

# Copiar primero el archivo de dependencias para aprovechar la caché de Docker
COPY requirements.txt .

# Instalar las dependencias de Python
RUN pip install --no-cache-dir -r requirements.txt

# Copiar el resto del código de tu aplicación al contenedor
COPY . .

# Comando para ejecutar la aplicación usando Uvicorn
# Render inyecta dinámicamente la variable de entorno $PORT, por lo que la leemos aquí.
# NOTA: Asegúrate de que tu archivo principal se llame 'main.py'. 
# Si se llama diferente (ej. 'api.py'), cambia 'main:app' por 'api:app'.
CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}"]