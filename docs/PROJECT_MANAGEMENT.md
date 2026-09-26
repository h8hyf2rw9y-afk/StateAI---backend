# STATEAI — Project Management

Última actualización: 25 de septiembre de 2026

- **Inicio formal del proyecto:** 25 de septiembre de 2026.
- **Línea base:** el trabajo construido antes de esta fecha se registra como entregado y sirve como punto de partida.
- **Fecha límite de lanzamiento público:** 25 de noviembre de 2026.
- **Ventana total:** 2 meses calendario.

## Visión

STATEAI es un CRM AI-first para profesionales y equipos inmobiliarios. Centraliza contactos, propiedades, requisitos de compradores, oportunidades, actividades, tareas, citas y recomendaciones de IA.

Renova es un flujo de adquisición de vivienda separado del CRM tradicional. Comparte la navegación de Leads, pero conserva su propio modelo, API, pipeline, controles de privacidad y auditoría.

## Principios del producto

- Multi-tenant: toda consulta se aísla por `organization_id`.
- Seguridad por diseño: NSS, número de crédito e INE no se exponen al LLM.
- IA con herramientas delimitadas: el modelo interpreta; FastAPI valida y consulta.
- Confirmación humana antes de cualquier modificación iniciada desde IA.
- Route → Service → Repository, Pydantic v2 y SQLAlchemy 2.0.
- Cambios pequeños, probados, revisables y desplegables por sprint.

## Estado actual

### Entregado

- Autenticación con Supabase y rutas protegidas.
- CRM base: contactos, propiedades, requisitos, intereses, oportunidades, actividades, tareas, citas y notificaciones.
- Agentes Lead Intelligence, Follow-up y Pipeline.
- Persistencia de ejecuciones de IA, detección de resultados obsoletos e idempotencia.
- Renova separado del CRM tradicional.
- Expedientes Renova con cifrado y acceso auditado a datos sensibles.
- INE cifrada, ficha compartible, dirección, ocupación, borradores y dúplex.
- Pipeline Kanban de Renova y archivado sin eliminación.
- Chat Renova de solo lectura con conversaciones persistentes y contexto por propietario.
- Pruebas automatizadas de backend y frontend, lint, tipos y build.

### Limitaciones conocidas

- El chat no consulta archivados.
- El resumen de pipeline mezcla estados activos con rechazados/cancelados.
- Debe verificarse que el chat nunca sume años de predial como pesos.
- El chat no ejecuta cambios de etapa.
- Dashboard aún usa datos simulados en varias tarjetas.
- Faltan flujos completos de creación/edición para citas, tareas y oportunidades.
- Sales Copilot sigue pendiente.
- Faltan E2E reales de autenticación y sesión.

## Método de trabajo

Se usan sprints de dos semanas, de lunes a viernes. El proyecto inicia formalmente el viernes 25 de septiembre con una fase corta de arranque y levantamiento de línea base; el primer sprint completo comienza el lunes 28.

### Ceremonias

- Planning: seleccionar un objetivo y trabajo que quepa en la capacidad.
- Daily: actualizar estado, bloqueo y siguiente paso.
- Review: demostrar criterios de aceptación con evidencia.
- Retrospective: registrar qué conservar, cambiar y probar.
- Refinement: preparar el siguiente sprint y dividir items demasiado grandes.

### Flujo del tablero

`Backlog → Ready → In progress → In review → Done`

Límites recomendados:

- Máximo 2 items simultáneos en `In progress`.
- Ningún item entra a sprint sin criterios de aceptación.
- Bugs de seguridad o pérdida de datos tienen prioridad P0/P1.
- Un item bloqueado debe indicar dependencia y responsable.

### Definition of Ready

- Problema y resultado esperado claros.
- Alcance y fuera de alcance descritos.
- Criterios de aceptación verificables.
- Dependencias identificadas.
- Estimación asignada.

### Definition of Done

- Código en rama y PR revisable.
- Pruebas añadidas o actualizadas.
- Lint, tipos, tests y build aprobados según corresponda.
- Migración verificada cuando aplique.
- Seguridad multi-tenant y privacidad revisadas.
- Documentación actualizada.
- Aceptación demostrada y merge a `main`.

## Plan de sprints

### Inicio y línea base — 25–27 sep 2026

Objetivo: formalizar el arranque, inventariar lo ya construido, configurar el tablero, confirmar ambientes y priorizar el primer riesgo operativo. Las capacidades ya implementadas se conservan en `Done`; no se reinterpretan como trabajo realizado dentro del nuevo calendario.

Hito de salida: backlog priorizado, flujo definido, documentación vigente y bug del 404 del Chat Renova listo para atender.

### Sprint 1 — Confiabilidad del Chat Renova
28 sep–9 oct 2026

Objetivo: que las respuestas existentes sean correctas y consistentes antes de permitir escritura.

Incluye:

- Consultar expedientes archivados.
- Separar pipeline activo de rechazados/cancelados.
- Tratar predial en años sin sumarlo como MXN.
- Aclarar el alcance del “resumen completo”.
- Añadir regresiones automatizadas.

### Sprint 2 — Acciones seguras desde el chat
12–23 oct 2026

Objetivo: permitir el primer cambio de datos desde IA con confirmación y auditoría.

Incluye:

- Intención `change_case_status`.
- Resolución de nombres ambiguos.
- Confirmación/cancelación explícita.
- Validación de transiciones y organización.
- Auditoría del estado anterior/nuevo.
- Interfaz de confirmación y pruebas.

### Sprint 3 — Operación real del CRM
26 oct–6 nov 2026

Objetivo: retirar datos simulados de las superficies operativas principales.

Candidatos:

- Dashboard con oportunidades, contactos, citas y tareas reales.
- Crear/editar/cancelar citas y tareas.
- Crear oportunidades desde Pipeline.
- Selector de responsables cuando exista el endpoint de usuarios.

### Sprint 4 — Preparación para producción
9–20 nov 2026

Objetivo: convertir el producto funcional en un servicio público operable y seguro.

Incluye:

- Infraestructura y despliegue reproducible de producción.
- Auditoría de seguridad, privacidad y aislamiento multi-tenant.
- Observabilidad, alertas, respaldos y recuperación.
- Onboarding, recuperación de acceso y estados de error accionables.
- Pruebas E2E de los recorridos críticos y corrección de bloqueadores.

### Ventana de estabilización y lanzamiento
21–25 nov 2026

- 21–24 nov: congelamiento funcional, regresión, smoke tests, documentación, soporte y decisión go/no-go.
- **25 nov: lanzamiento público de STATEAI.**
- Regla de salida: cero P0 abiertos; cualquier P1 restante debe tener mitigación y decisión explícita.
- Las funcionalidades no indispensables que amenacen la fecha regresan al backlog posterior al lanzamiento.

### Roadmap posterior al lanzamiento

- Sales Copilot.
- Detección temporal de actividades vencidas/próximas y productores de notificaciones.
- Resultados de Appointment vinculados a Activity.
- Matching inverso Property → Buyer Requirement.
- Postventa.
- Routing configurable entre Ollama y proveedores API.
- Paginación, preferencias de perfil, recuperación de contraseña, tema y E2E.

## Convenciones de issues

Cada issue debe incluir:

- Tipo: Epic, Feature, Bug, Tech debt, Security, Documentation o Test.
- Área: Backend, Frontend, AI, Renova, CRM, Platform o QA.
- Prioridad: P0, P1, P2 o P3.
- Estimación: 1, 2, 3, 5, 8 o 13 puntos.
- Sprint: iteración comprometida o Backlog.
- Criterios de aceptación.
- Dependencias y riesgos.

## Política para IA con escritura

Las acciones de IA no reciben acceso directo a SQL. El LLM propone una herramienta tipada; el backend valida usuario, organización, permisos, entidad y transición. Toda acción sensible requiere confirmación humana, idempotencia y auditoría. NSS, número de crédito e imágenes INE permanecen fuera del contexto del modelo.

## Métricas sugeridas

- Velocidad: puntos terminados por sprint.
- Predictibilidad: comprometido vs. terminado.
- Lead time: Ready → Done.
- Calidad: bugs reabiertos y regresiones.
- Salud: items bloqueados y edad del backlog.
- Producto: consultas exitosas, ambigüedades y confirmaciones canceladas.
- Lanzamiento: disponibilidad, tasa de errores, activación de usuarios y tiempo de recuperación.

## Hitos ejecutivos

| Hito | Fecha | Evidencia de salida |
|---|---:|---|
| Inicio formal y línea base | 25 sep 2026 | Tablero, documentación y backlog creados |
| Chat Renova confiable | 9 oct 2026 | Regresiones aprobadas y 404 resuelto |
| Primera acción segura desde IA | 23 oct 2026 | Confirmación, permisos y auditoría demostrados |
| CRM operativo con datos reales | 6 nov 2026 | Flujos críticos sin mocks |
| Producción lista | 20 nov 2026 | Seguridad, despliegue, observabilidad y onboarding aprobados |
| Lanzamiento público | **25 nov 2026** | Acceso habilitado, smoke tests y monitoreo activos |

