# Part 4 — Value Model Integration (Design)

The data science team has built a predictive model that scores each renter on their likelihood to convert. The model outputs a daily BigQuery table:

```sql
CREATE TABLE ml_predictions.renter_send_scores (
  renter_id STRING,
  predicted_conversion_probability FLOAT64,  -- 0.0 to 1.0
  model_version STRING,
  scored_at TIMESTAMP
);
```

**Requirement:** Only send the reactivation SMS to renters whose predicted conversion probability exceeds a configurable threshold (e.g., 0.3).

**Additional context:** A second predictive model for a different user segment is expected in approximately 6 weeks. Your design should support multiple models with different thresholds per segment without requiring rearchitecture.

## Task

Describe (in writing or pseudocode) how you would modify:

1. The **BigQuery query** from Part 1 to incorporate model scores
2. The **Airflow DAG** from Part 3 to add a dependency on the model scoring table being fresh (scored today)
3. How you would handle the case where the **model scoring job hasn't completed** by the time the campaign DAG runs

## Evaluation Criteria

- Clean integration of model scores into the audience query (JOIN pattern, threshold parameterization)
- DAG dependency management (sensor or external task dependency for model freshness)
- Graceful handling of model pipeline delays (wait vs. skip vs. fallback)
- Shows understanding of the business tradeoff: sending without model scores wastes volume, not sending at all loses revenue

# Part 4 — Value Model Integration (Design Considerations & Assumptions)

## 1. Data Freshness (Critical Dependency)
- The campaign depends on `ml_predictions.renter_send_scores`.
- Only scores generated **on the same `run_date`** are considered valid.
- Using stale scores may degrade targeting quality.

---

## 2. Latest Score per Renter
- The table may contain multiple rows per `renter_id` due to:
  - multiple scoring runs
  - different `model_version`

Assumption:
- Use the **latest score per renter** based on `scored_at`.

---

## 3. Model Versioning
- Multiple model versions may exist simultaneously.
- The campaign must explicitly define which model to use.

Assumption:
- Model selection is configurable (e.g., via `model_version` parameter).

---

## 4. Threshold Parameterization
- The conversion threshold (e.g., `0.3`) is configurable.
- It must not be hardcoded in the query.

Assumption:
- Threshold is passed via Airflow config or query parameter.

---

## 5. Multi-Model Support (Future Requirement)
- Additional models will be introduced for different segments.

Design requirement:
- Support:
  - multiple models
  - different thresholds per model
  - segment-based targeting

Assumption:
- Configuration drives:
  - model selection
  - threshold per segment

---

## 6. Join Integrity
- Joining predictions incorrectly can lead to:
  - duplicated renters
  - inconsistent audience size

Constraint:
- Ensure a **1:1 join** between renters and their score.

---

## 7. Missing Predictions
- Some renters may not have a score.

Assumption:
- Renters without a score are **excluded** from the campaign.

Alternative (not implemented here):
- fallback score
- separate treatment group

---

## 8. Dependency on ML Pipeline
- The campaign depends on the model scoring job being completed.

Constraint:
- Must verify that scores for the current `run_date` are available.

Typical approach:
- BigQuery freshness check
- Airflow sensor

---

## 9. SLA Conflict
- Campaign runs at 5:00 AM UTC.
- Model scoring job may complete later.

Tradeoff:
- Wait → risk missing SLA
- Skip → lose revenue
- Fallback → lower targeting quality

---

## 10. Fallback Strategy
Assumption:
- Use **bounded waiting**:
  - wait up to a defined timeout (e.g., 30–60 minutes)
  - if scores are still unavailable:
    - fallback to sending without model filtering **or**
    - skip campaign (configurable)

---

## 11. Idempotency & Consistency
- Model scores may change during the day if recomputed.

Constraint:
- The campaign must use a **consistent snapshot** of scores per `run_date`.

---

## 12. Performance Considerations
- Joining large tables (activity, profiles, predictions) can be expensive.

Best practices:
- filter early
- reduce dataset before joining
- use partitioning on `scored_at`

---

## 13. Observability
- Track:
  - number of renters filtered by model
  - score distribution
  - threshold impact on audience size

---

## 14. Business Tradeoff (Key Insight)
- Sending without model filtering:
  - wastes SMS volume
- Not sending:
  - loses potential revenue

Assumption:
- Model dependency is treated as a **soft dependency with bounded waiting**, not a hard requirement.
```
