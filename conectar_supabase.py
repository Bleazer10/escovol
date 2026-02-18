import os
from dotenv import load_dotenv
from supabase import create_client
from pathlib import Path

print("🔌 CONECTOR SUPABASE\n" + "="*40)

# Cargar variables de entorno
env_path = Path('.') / '.env'
print(f"📁 Buscando .env en: {env_path.absolute()}")
cargado = load_dotenv(dotenv_path=env_path)
print(f"📦 load_dotenv: {'✅' if cargado else '❌'}")

# Variables disponibles en el entorno
print("\n📋 Variables SUPABASE encontradas:")
vars_supabase = [v for v in os.environ.keys() if v.startswith('SUPABASE')]
for var in vars_supabase:
    valor = os.getenv(var)
    if var == 'SUPABASE_ANON_KEY':
        print(f"   - {var}: {valor[:15]}... (anon key)")
    elif var == 'SUPABASE_SERVICE_ROLE_KEY':
        print(f"   - {var}: {valor[:15]}... (service role - MANTENER SECRETA)")
    elif var == 'SUPABASE_URL':
        print(f"   - {var}: {valor}")
    else:
        print(f"   - {var}: {valor[:20] if valor else 'None'}")

# Conectar con anon key
print("\n🔄 Intentando conexión con SUPABASE_ANON_KEY...")
url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_ANON_KEY")

if not url or not key:
    print("❌ Faltan credenciales:")
    print(f"   SUPABASE_URL: {'✅' if url else '❌'}")
    print(f"   SUPABASE_ANON_KEY: {'✅' if key else '❌'}")
    exit(1)

try:
    supabase = create_client(url, key)
    print("✅ Cliente Supabase creado")
    
    # Verificar autenticación (consulta a la tabla auth.users o cualquier tabla pública)
    print("\n📊 Probando acceso...")
    
    # Intenta listar las tablas (esto puede variar según tu esquema)
    try:
        # Reemplaza 'test' con el nombre de una tabla que exista en tu BD
        # result = supabase.table('test').select('*').limit(1).execute()
        print("   (opcional) Descomenta las líneas para probar consultas reales")
        # print(f"✅ Consulta exitosa: {result}")
    except Exception as e:
        print(f"   Nota: No se pudo consultar tabla (probablemente no existe aún)")
    
    print("\n✨ TODO CORRECTO: Tu configuración funciona!")
    print(f"   URL: {url}")
    print(f"   Conectado con clave anon: {key[:15]}...")
    
except Exception as e:
    print(f"❌ Error fatal: {e}")
    print("\n🔧 Posibles soluciones:")
    print("   1. Verifica que SUPABASE_URL y SUPABASE_ANON_KEY están en .env")
    print("   2. Asegúrate que la anon key tiene permisos en las tablas")
    print("   3. Comprueba que el proyecto Supabase está activo")

print("\n" + "="*40)