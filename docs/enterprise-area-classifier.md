# Enterprise Area Classifier

Sentinel now classifies remembered transcripts by enterprise area and segments tasks by likely business role.

## What It Detects

The classifier recognizes common business areas:

- Direccion Ejecutiva
- Recursos Humanos
- Seguridad
- Tecnologia / TI
- Finanzas
- Legal y Cumplimiento
- Ventas y Clientes
- Marketing
- Operaciones y Logistica
- Producto e Ingenieria
- Datos y Analitica
- Atencion al Cliente
- Instalaciones
- Salud

## How It Works

This is local ML-style classification using the same deterministic vectorizer used by Sentinel's vector memory.

```text
safe transcript
-> local embedding
-> compare against enterprise area prototypes
-> return ranked areas with evidence
-> classify each extracted task
-> assign task area and role
```

No external AI call is required. The raw transcript remains local.

## API Fields

Memory responses include:

```json
{
  "areas": [
    {
      "area": "Seguridad",
      "score": 0.42,
      "evidence": ["secops", "credenciales", "revocar"]
    }
  ],
  "task_segments": [
    {
      "description": "SecOps debe revocar credenciales comprometidas.",
      "area": "Seguridad",
      "role": "Seguridad / SecOps",
      "confidence": 0.58
    }
  ]
}
```

The frontend shows these under saved memory details as `Areas` and `Tasks by Role`.
