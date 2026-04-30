# Cloud setup

Current shared project:

```text
Project ID: smartstudy-h505
Region: europe-west1
PDF bucket: gs://smartstudy-h505-pdfs/
Budget alert: SmartStudy_budget
```

Enabled APIs:

- Cloud Storage
- Cloud Functions
- Cloud Build
- Eventarc
- Cloud Run
- Vertex AI

Team access is handled through Google Cloud IAM. Teammates should use their own Google accounts. Do not share a personal login.

## Bucket smoke test

Run this in Google Cloud Shell while project `smartstudy-h505` is selected:

```bash
echo "SmartStudy bucket smoke test" > smoke-test.txt
gcloud storage cp smoke-test.txt gs://smartstudy-h505-pdfs/smoke-test.txt
gcloud storage ls gs://smartstudy-h505-pdfs/
gcloud storage rm gs://smartstudy-h505-pdfs/smoke-test.txt
rm smoke-test.txt
```

Expected result: the file appears in the bucket listing before it is removed.

Status: passed on 2026-04-30.
