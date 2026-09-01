# StateAI — Backend

StateAI (también referido como **PropPilot**) es un CRM impulsado por IA diseñado específicamente para profesionales inmobiliarios. Su objetivo es centralizar todo el proceso de ventas — desde la gestión de propiedades y leads hasta la programación de citas, el seguimiento de oportunidades y el contacto con potenciales compradores.

A diferencia de los CRMs tradicionales, que se limitan a almacenar información, StateAI está diseñado para asistir activamente a los agentes inmobiliarios. Agentes de IA analizan leads, identifican prioridades, recomiendan próximas acciones, automatizan seguimientos, organizan la información de los clientes y ayudan a mover oportunidades a través del pipeline de ventas.

El objetivo final es reducir el trabajo administrativo asociado a las ventas inmobiliarias y permitir que los agentes dediquen más tiempo a construir relaciones, negociar y cerrar tratos.

Este repositorio contiene el **backend** del proyecto (la API y la lógica de servidor). El frontend vive en un repositorio/carpeta separado.

## Objetivos del proyecto

1. **Centralizar el proceso de ventas** — una única plataforma donde los agentes gestionen propiedades, leads, clientes, citas, conversaciones y negociaciones.
2. **Mejorar la gestión de leads** — ayudar a organizar y priorizar leads según sus intereses, comportamiento, presupuesto y probabilidad de conversión.
3. **Automatizar el trabajo repetitivo** — usar agentes de IA para automatizar tareas como seguimientos, recordatorios, calificación de leads, coordinación de citas y actualización del CRM.
4. **Proveer insights accionables** — en lugar de solo mostrar datos, indicar a los agentes qué acciones tomar y qué oportunidades merecen su atención.
5. **Aumentar las tasas de conversión** — reducir oportunidades perdidas asegurando que los leads calificados reciban seguimiento oportuno y personalizado.
6. **Construir un CRM AI-first** — ir más allá del modelo tradicional de CRM hacia un sistema donde la IA participa activamente en la gestión del pipeline de ventas.
7. **Crear una plataforma escalable** — sentar las bases de un producto SaaS que eventualmente soporte agentes individuales, equipos inmobiliarios y agencias.

## Estado del proyecto

🚧 Este backend está en fase inicial — el repositorio aún no contiene código. Este README sirve como punto de partida y se irá completando a medida que se defina la arquitectura.

## Autenticación (Supabase) — a tener en cuenta para este backend

El frontend (`stateai-frontend`) ya implementa autenticación real con **Supabase Auth** (email/contraseña + Google OAuth vía `@supabase/ssr`), sin este backend de por medio — Supabase actúa como proveedor de identidad directamente. Esto tiene implicaciones importantes para cuando se construya FastAPI:

- **El backend deberá verificar el JWT de Supabase en cada request.** El frontend protege sus rutas con un Proxy/Middleware de Next.js, pero esa es solo una comprobación optimista del lado del cliente — no es un límite de seguridad real. Este backend **no debe confiar** en que una request ya viene autenticada solo porque el frontend la dejó pasar; debe validar el JWT (firma, expiración, `aud`/`iss`) de forma independiente en cada endpoint protegido.
- **Variables de entorno que este backend necesitará** (no confundir con las del frontend):
  - `SUPABASE_URL` — la misma URL del proyecto que usa el frontend.
  - `SUPABASE_SERVICE_ROLE_KEY` — clave secreta con acceso administrativo total, **solo para este backend**. Nunca debe existir en el frontend ni en ningún código que corra en el navegador.
  - Posiblemente `SUPABASE_JWT_SECRET` (o las claves públicas JWKS del proyecto) para verificar tokens sin llamar a la API de Supabase en cada request.
- **Ya existen usuarios reales en `auth.users`** con metadata poblada por el frontend:
  - Registro por email: `user_metadata.first_name`, `user_metadata.last_name`.
  - Google OAuth: `user_metadata.full_name` (o `name`), `user_metadata.avatar_url` (o `picture`).
  - Esto es útil como referencia al diseñar una futura tabla pública `profiles`/`users` (con Row Level Security) que este backend gestione — actualmente **no existe ninguna tabla de aplicación**, solo la tabla interna `auth.users` que administra Supabase.
- **El frontend ya modela el dominio `Organization → Team → User`** en `types/user.ts` (sin implementación real, solo tipos), anticipando el multi-tenancy que este backend deberá construir sobre Supabase Auth (por ejemplo, una tabla `organizations`/`teams`/`profiles` con `auth.users.id` como referencia).
- **Nunca** expongas `SUPABASE_SERVICE_ROLE_KEY` en logs, respuestas de la API, ni en ningún artefacto que llegue al frontend.

Más detalle de la implementación (para consulta, no para duplicar aquí) está documentado en el README del frontend, sección "How authentication works" / "Supabase configuration".

## Stack tecnológico

- **Framework de API**: FastAPI (planeado — _aún no implementado_, ver regla "Do NOT build FastAPI yet" en las instrucciones del proyecto).
- **Autenticación**: Supabase Auth (ya en uso desde el frontend; este backend deberá verificar sus JWTs — ver sección anterior).
- **Base de datos**: Supabase PostgreSQL (planeado — _aún no hay tablas de aplicación_).
- El resto del stack (ORM, migraciones, etc.) _aún no definido_.

## Estructura del proyecto

_TODO: se documentará una vez definida la arquitectura (por ejemplo, capas de API, dominio, agentes de IA, persistencia, etc.)._

## Cómo empezar

_TODO: instrucciones de instalación y ejecución una vez que exista código base._
