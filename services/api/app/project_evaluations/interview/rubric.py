from services.api.app.project_evaluations.domain.models import RubricCriterion

DEFAULT_RUBRIC = [
    RubricCriterion.EVIDENCE_ALIGNMENT,
    RubricCriterion.IMPLEMENTATION_SPECIFICITY,
    RubricCriterion.STRUCTURAL_UNDERSTANDING,
    RubricCriterion.DECISION_UNDERSTANDING,
    RubricCriterion.TROUBLESHOOTING_EXPERIENCE,
    RubricCriterion.LIMITATION_AWARENESS,
    RubricCriterion.ANSWER_CONSISTENCY,
]
