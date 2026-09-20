# Hosting ZeroQueue on AWS EC2

This guide puts the one-container FastAPI app on a small Ubuntu server. AWS account rules and free-tier eligibility vary, so confirm the price shown in the AWS console before launching. Stop or terminate the server when you no longer need it.

## 1. Launch the server

1. Sign in to the AWS console and open **EC2**.
2. Choose **Launch instance**.
3. Name it `zeroqueue-demo`.
4. Choose **Ubuntu Server 24.04 LTS**, 64-bit x86.
5. Choose an instance type that the console marks free-tier eligible for your account, commonly `t2.micro` or `t3.micro`.
6. Create a new `.pem` key pair and download it. AWS shows the private key only once.
7. In **Network settings**, allow SSH from **My IP**. Do not open SSH to the whole internet.
8. Launch the instance. Wait until Instance state is **Running** and both status checks pass.

## 2. Open the app port

1. Select the instance and open its attached **Security group**.
2. Edit inbound rules.
3. Add **Custom TCP**, port `8000`.
4. For a private rehearsal, choose **My IP**. For a public demo link, choose `0.0.0.0/0` temporarily, then remove that rule after the demo.
5. Save rules.

## 3. Connect and install Docker

From Windows PowerShell in the folder holding the downloaded key:

```powershell
ssh -i .\zeroqueue-demo.pem ubuntu@YOUR_EC2_PUBLIC_IP
```

On the Ubuntu server:

```bash
sudo apt-get update
sudo apt-get install -y docker.io docker-compose-v2 unzip
sudo usermod -aG docker ubuntu
exit
```

Connect again so the Docker group change takes effect:

```powershell
ssh -i .\zeroqueue-demo.pem ubuntu@YOUR_EC2_PUBLIC_IP
```

Verify:

```bash
docker --version
docker compose version
```

## 4. Copy the project

On your Windows machine, keep `.env` private. Copy the project folder to EC2:

```powershell
scp -i .\zeroqueue-demo.pem -r E:\Hackathons\zeroqueue-hubble ubuntu@YOUR_EC2_PUBLIC_IP:/home/ubuntu/
```

This also copies `.env`. Do not push `.env` to GitHub or place its values in commands, screenshots, or logs. A safer production setup would use AWS Secrets Manager, but a private `.env` is simpler for this short demo.

## 5. Build and start

Back in the EC2 SSH terminal:

```bash
cd ~/zeroqueue-hubble
docker compose up --build -d
```

Check it:

```bash
docker compose ps
docker compose logs --tail=100
curl http://localhost:8000/health
```

Open this in your browser:

```text
http://YOUR_EC2_PUBLIC_IP:8000
```

If it does not open, confirm the container is healthy and the EC2 security-group rule allows TCP 8000 from your current IP.

## 6. Update or stop

After replacing project files:

```bash
cd ~/zeroqueue-hubble
docker compose down
docker compose up --build -d
```

Stop without deleting the instance:

```bash
docker compose down
```

In the AWS console, stop the EC2 instance when the demo is over. Storage can still cost money while stopped. Terminate the instance when you no longer need it.

## Optional Elastic IP

A normal EC2 public IP can change after stop/start. To keep one address, open **EC2 -> Elastic IPs**, allocate an address, and associate it with this instance. AWS may charge for unused or certain Elastic IP configurations, so release it after the demo if you no longer need it.

## Intercom webhook on EC2

Once port 8000 is publicly reachable, the webhook URL is:

```text
http://YOUR_EC2_PUBLIC_IP:8000/api/webhooks/intercom
```

Intercom should use HTTPS in a real deployment. For demo day, use ngrok against the EC2/local port or put a domain plus TLS reverse proxy in front of FastAPI. Keep the Intercom token and webhook secret only in the server's private `.env`.

## Render: five-minute alternative

For the quickest demo-day deployment, create a Render **Web Service** from the public GitHub repository, choose the repository's root `Dockerfile`, and add each `.env` value in Render's Environment settings rather than uploading `.env`. Render builds the Docker image and gives you an HTTPS URL. Use that URL for the page and `/api/webhooks/intercom`. Free-plan availability, sleep behavior, build time, and pricing can change, so check the current Render plan before relying on it for a timed judging session and wake the service before recording.

## Official references

- AWS Linux SSH: https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/connect-linux-inst-ssh.html
- AWS security groups: https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/ec2-security-groups.html
- AWS Elastic IP association: https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/working-with-eips.html
- Render Docker deploys: https://render.com/docs/docker
- Render environment variables and secrets: https://render.com/docs/configure-environment-variables
