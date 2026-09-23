QUESTIONS = {
    "event_type": {
        "type": "choice",
        "instructions": "What is the primary incident type?",
        "criteria": {
            "mechanical": "Noise, vibration, friction, alignment, bearing, structural, or moving-part issue.",
            "electrical": "Power, wiring, motor, short circuit, arcing, or electrical protection issue.",
            "process": "Pressure, flow, temperature, quality, containment, or operating-process deviation.",
            "instrumentation": "Sensor, control, calibration, automation, or measurement issue.",
            "environmental": "Leak, spill, emission, contamination, or environmental-control issue.",
            "unknown": "The report does not support a clear category.",
        },
    },
    "operational_severity": {
        "type": "score",
        "instructions": "How severe is the current operational condition?",
        "criteria": [
            "Observation only; stable and within normal operating limits.",
            "Degraded; abnormal but stable, with limited operational impact.",
            "Serious; worsening condition, likely damage, or major service interruption.",
            "Critical; immediate threat to people, environment, or asset integrity.",
        ],
    },
    "evidence_sufficiency": {
        "type": "score",
        "instructions": "How sufficient is the evidence for selecting an operational route?",
        "criteria": [
            "Insufficient; only a vague report and no corroborating evidence.",
            "Partial; useful evidence exists but important checks are missing.",
            "Sufficient; multiple relevant observations support a route.",
        ],
    },
    "requires_immediate_isolation": {
        "type": "noul",
        "instructions": "Does the available evidence support immediately isolating the asset pending human confirmation?",
        "criteria": {
            "true": "Continued operation may rapidly worsen damage or create a safety or environmental hazard.",
            "false": "Monitoring or planned investigation is reasonable while the asset remains in service.",
        },
    },
    "likely_safety_impact": {
        "type": "noul",
        "instructions": "Does this incident plausibly threaten human safety?",
        "criteria": {
            "true": "Evidence indicates injury, fire, uncontrolled energy, dangerous temperature, structural failure, or exposure.",
            "false": "No meaningful human-safety pathway is indicated.",
        },
    },
    "likely_environmental_impact": {
        "type": "noul",
        "instructions": "Does this incident plausibly have an environmental impact?",
        "criteria": {
            "true": "Evidence indicates a leak, spill, emission, contamination, or failed containment.",
            "false": "No environmental-release pathway is indicated.",
        },
    },
    "recommended_route": {
        "type": "choice",
        "instructions": "Which team should receive the incident first?",
        "criteria": {
            "monitor": "Operations can monitor a stable low-severity condition.",
            "maintenance": "A known or likely equipment defect needs maintenance inspection.",
            "engineering": "The cause is ambiguous or requires specialist diagnosis.",
            "emergency": "Immediate coordinated safety, environmental, or incident response is indicated.",
        },
    },
}

