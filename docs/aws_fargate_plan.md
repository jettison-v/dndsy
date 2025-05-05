# AWS Fargate Processing Pipeline Plan

This document outlines the planned AWS infrastructure setup for moving the PDF processing workload to a scalable, asynchronous pipeline using AWS Fargate.

**Goal:** Decouple heavy processing from the main web application, enabling scalable, robust, and event-driven handling of PDF uploads.

## Rationale for Architecture

*   **Problem:** The existing data processing workflow (PDF parsing, text/image/link extraction, metadata generation via LLM, vector store population) takes significantly longer than the 15-minute limit for AWS Lambda functions, as confirmed by logs.
*   **Why Fargate?** AWS Fargate is a serverless compute engine for containers that does not have Lambda's execution time limits. It's suitable for long-running batch processing tasks like this one.
*   **Why SQS?** Amazon SQS provides a reliable queue to decouple the PDF upload event (from S3) from the Fargate processing task. This ensures uploads are fast for the user, and processing happens asynchronously. It also allows for automatic retries and a Dead-Letter Queue (DLQ) for handling persistent processing failures.
*   **Why S3 Events?** Using S3 Event Notifications (`s3:ObjectCreated:*`) automatically triggers the SQS message when a PDF is uploaded to the designated prefix, creating an event-driven workflow.
*   **Why Containerization (`Dockerfile.worker`)?** Packaging the worker script and its dependencies (Python libs, system tools like Rust for `tiktoken`) ensures a consistent runtime environment that matches local development and simplifies deployment to Fargate.
*   **Why ECR?** Amazon ECR is the standard AWS service for storing and managing Docker container images.
*   **Why Secrets Manager?** Securely stores sensitive configurations like API keys, preventing them from being hardcoded or stored insecurely in environment variables.
*   **Why IAM Roles?** Follows the principle of least privilege, granting the Fargate task only the specific permissions needed to access SQS, S3, Secrets Manager, and CloudWatch.
*   **Why VPC Endpoints (Recommended)?** Improves security and potentially reduces costs by keeping traffic between Fargate and other AWS services (S3, SQS, ECR, Secrets Manager, CloudWatch Logs) within the AWS network.
*   **Benefits:** This architecture provides scalability (Fargate Auto Scaling based on queue depth), reliability (SQS retries, DLQ), decoupling (web app isn't blocked), and better resource utilization (scales to zero when idle).

## Codebase Context & Refactoring Summary

*   **Core Processing:** The main logic resides in `data_ingestion/processor.py` within the `DataProcessor` class. It handles PDF download, hashing, image generation/upload (S3), text/link extraction, structure analysis, LLM-based metadata generation (`_generate_and_upload_metadata`), and populating vector stores.
*   **Metadata Generation:** Logic from the original standalone `metadata_processor.py` was found to be integrated directly within `data_ingestion/processor.py`.
*   **Triggering (Original):** Processing was likely initiated via `scripts/manage_vector_stores.py`, which instantiated `DataProcessor` and called its `process_all_sources` method, iterating through all PDFs in S3.
*   **Configuration:** A hybrid approach was identified and refined:
    *   Application tuning parameters (LLM temp, retrieval K, prompts, etc.) are managed via `config.app_config`, loaded from S3 (`config/app_config.json`) with defaults in `config.py`.
    *   Infrastructure details (S3 bucket, Qdrant host) and Secrets (API keys) are managed via environment variables (expected to be set via `.env` locally, platform variables/secrets on Railway/AWS).
*   **Refactoring Steps Performed (in `feature/cloud-processing` branch):**
    1.  Added `DataProcessor.process_single_source()` method to handle end-to-end processing for a single specified S3 PDF key.
    2.  Created `Dockerfile.worker` tailored for the Fargate task.
    3.  Created `fargate_worker.py` with SQS polling logic, using `DataProcessor.process_single_source()`.
    4.  Refactored `scripts/manage_vector_stores.py` to act as a bulk SQS trigger (listing PDFs and sending messages) instead of running `DataProcessor` directly.
    5.  Parameterized Qdrant collection names in vector store implementations (`pdf_pages_store.py`, `semantic_store.py`, `haystack/qdrant_store.py`) using environment variables (`QDRANT_PAGES_COLLECTION`, etc.) with original names as fallbacks.
    6.  Audited `config.py` and confirmed its alignment with the hybrid configuration approach.
    7.  Confirmed `app.py` upload/admin trigger endpoints are compatible with the new SQS-based workflow.

## AWS Infrastructure Plan (Core Components)

1.  **S3 Bucket (`your-bucket-name`):**
    *   Stores source PDFs (`source-pdfs/`), metadata (`pdf-metadata/`), page images (`pdf_page_images/`), link data (`extracted_links/`), and processing history (`processing/`).
    *   **Event Notification:** Configured for `s3:ObjectCreated:*` on `.pdf` files under `source-pdfs/`, sending notifications to the SQS Queue.

2.  **SQS Queue (`your-processing-queue`):**
    *   Acts as a task queue, receiving notifications from S3.
    *   Standard queue type.
    *   **Visibility Timeout:** Set long enough for max PDF processing time (e.g., 30-60 min).
    *   **Dead-Letter Queue (DLQ):** Configured (`your-processing-queue-dlq`) to catch persistently failing messages.
    *   **Permissions:** Allows S3 `SendMessage` and Fargate Task Role `Receive/Delete/GetAttributes`.

3.  **ECR Repository (`your-processing-worker`):**
    *   Stores the Docker image built from `Dockerfile.worker`.

4.  **AWS Secrets Manager:**
    *   Stores sensitive values like LLM API keys, Qdrant API key.
    *   Fargate Task Role needs `secretsmanager:GetSecretValue` permission.

5.  **IAM Task Role (`your-fargate-task-role`):**
    *   Role assumed by the Fargate worker container.
    *   **Permissions:** SQS receive/delete, S3 get/put/delete/list (scoped to bucket/prefixes), Secrets Manager get value, CloudWatch Logs put events.
    *   **Trusts:** `ecs-tasks.amazonaws.com`.

6.  **ECS Cluster (`your-processing-cluster`):**
    *   Logical grouping for the service.
    *   Uses Fargate launch type.

7.  **ECS Task Definition (`your-processing-worker-task`):**
    *   Defines the worker task.
    *   **Launch Type:** Fargate.
    *   **Roles:** Assigns Task Role (Step 5) and Execution Role (`ecsTaskExecutionRole`).
    *   **Container:** Uses the ECR image (Step 3), defines CPU/Memory, Environment Variables (pulling secrets from Secrets Manager), and CloudWatch logging.

8.  **ECS Service (`your-processing-service`):**
    *   Manages running and scaling the worker tasks.
    *   **Launch Type:** Fargate.
    *   **Networking:** Uses private subnets in VPC, appropriate Security Group, Public IP disabled.
    *   **Auto Scaling:** Configured based on SQS `ApproximateNumberOfMessagesVisible` metric to scale tasks between a min (e.g., 0) and max count.

9.  **Networking (VPC):**
    *   Requires VPC with private and public subnets.
    *   **NAT Gateway/Instance:** For outbound internet access from private subnets (if needed for external APIs).
    *   **Security Group:** Allows necessary outbound traffic (HTTPS, Qdrant ports) from Fargate tasks.
    *   **VPC Endpoints (Recommended):** For S3, SQS, ECR, Secrets Manager, CloudWatch Logs to keep traffic within AWS network.

10. **CloudWatch:**
    *   **Logs:** Captures container logs from Fargate tasks.
    *   **Alarms:** Monitor SQS queue depth (main and DLQ), Fargate CPU/Memory, Service task count/health.

## Workflow Summary:

1.  PDF uploaded to `s3://your-bucket-name/source-pdfs/`.
2.  S3 sends event notification to `your-processing-queue`.
3.  ECS Service Auto Scaling potentially launches a Fargate task if messages are waiting and capacity allows.
4.  Fargate task starts, container runs `fargate_worker.py`.
5.  Worker script polls SQS, receives message (containing S3 key).
6.  Worker script executes `DataProcessor.process_single_source(s3_key, target_stores)`:
    *   Downloads PDF from S3.
    *   Performs preprocessing (image gen, text/link extraction).
    *   Generates metadata using LLM (via `_generate_and_upload_metadata`) & uploads to `pdf-metadata/`.
    *   Populates target vector stores (Qdrant) using preprocessed data.
    *   Updates `processing/pdf_process_history.json` in S3.
7.  Upon successful processing, worker deletes the message from SQS.
8.  If processing fails repeatedly, message goes to DLQ.
9.  Flask app admin panel (`/api/admin/process`) triggers bulk processing by calling `scripts/manage_vector_stores.py`, which lists PDFs and sends one SQS message per PDF.

## Outstanding Tasks / Next Steps:

1.  **AWS Resource Creation:** Provision the SQS queues, ECR repo, Secrets Manager secrets, IAM roles, ECS cluster/task definition/service, and networking components (VPC Endpoints recommended).
2.  **Deployment:** Build and push the worker image to ECR. Configure and deploy the ECS service.
3.  **Configuration:** Set environment variables and secrets correctly in the ECS Task Definition.
4.  **Status Monitoring:** Implement a mechanism for the Flask frontend to monitor the status of Fargate processing tasks (e.g., polling S3/DynamoDB, WebSockets/SSE, Step Functions).
5.  **Generalization (Prompts):** Review LLM prompts in `data_ingestion/processor.py` (metadata) and `llm.py` (chat) to ensure they are generic or configurable for non-D&D use cases.
6.  **Testing:** Thoroughly test the end-to-end flow (upload -> S3 -> SQS -> Fargate -> S3/Qdrant) and the bulk trigger script.

**(Note:** Replace placeholders like `your-bucket-name`, `your-processing-queue` etc. with actual resource names during implementation.) 