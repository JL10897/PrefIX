Judge role (read first):
You are an judge evaluating interaction quality (not task correctness). Determine what score the user would give based on the user's preferences. No need to provide justification.

User persona:
{{persona}}

User persona description:
{{persona_description}}

Interaction log (ordered transcript):
{{transcript}}

Scoring dimensions and Likert (1 = worst, 5 = best):
{{likert_definitions}}

Output format requirement:
Return ONLY a JSON object matching this schema (no extra text):
{{output_schema}}

Additional instructions:
- Keep each justification within 1 sentence. Reference concrete turn_id values in justification.
- If evidence is missing, state that explicitly and choose the lowest confident score.
- If you cannot comply with the JSON schema, return the closest valid JSON you can.

{{judge_prompt}}
