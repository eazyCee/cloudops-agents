To deploy, simply run:

gcloud run deploy [SERVICE_NAME]   --source .   --region us-central1   --allow-unauthenticated --env-vars-file=.env --port=8001