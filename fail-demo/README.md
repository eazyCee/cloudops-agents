# Fail Demo Cloud Run Service

This service is designed to demonstrate a failing deployment/startup in Google Cloud Run when a required environment variable is missing.

## Behavior

- **Failure Case**: If the environment variable `REQUIRED_CONFIG` is NOT set, the service logs an error and exits with code `1`. This causes Cloud Run to fail the deployment or instance startup.
- **Success Case**: If `REQUIRED_CONFIG` is set, the service logs the value and starts a dummy HTTP server on port 8080.

## How to test locally

### Simulate Failure
```bash
python main.py
```
Output should show the error and exit.

### Simulate Success
```bash
export REQUIRED_CONFIG="my-secret-value"
python main.py
```
Output should show success and start the server.

## How to Deploy to Cloud Run

### Build and Push Image
You can use Cloud Build to build and push the image to Artifact Registry.
```bash
gcloud builds submit --tag gcr.io/YOUR_PROJECT_ID/fail-demo .
```
*(Note: Replace `gcr.io` with your Artifact Registry path if preferred)*

### Deploy and Fail (Demonstration)
Deploy without setting the environment variable:
```bash
gcloud run deploy fail-demo \
  --image gcr.io/YOUR_PROJECT_ID/fail-demo \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated
```
This deployment should fail.

### Deploy and Succeed
Deploy with the environment variable:
```bash
gcloud run deploy fail-demo \
  --image gcr.io/YOUR_PROJECT_ID/fail-demo \
  --platform managed \
  --region us-central1 \
  --set-env-vars REQUIRED_CONFIG="working-fine" \
  --allow-unauthenticated
```
This deployment should succeed.
