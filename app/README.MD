To deploy, simply run:

gcloud run deploy a2a-agent   --source .   --region us-central1   --allow-unauthenticated --env-vars-file=.env --port=8001