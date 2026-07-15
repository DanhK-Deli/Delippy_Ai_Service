# Workspace Rules: Chatbot User State and Authentication Flow

To ensure any AI agent working on this repository handles user states correctly, we define the following rules for endpoint logic and tool execution:

## 1. User State Classification
Every incoming message to either `/api/v1/chat` or `/api/v1/help` must be classified into one of two states:
- **Authenticated User (Registered User):** Defined by the presence of a valid `Authorization` token in the request header.
- **Guest (Unauthenticated User):** Defined by the absence or empty value of the `Authorization` header.

## 2. API Tool Access Rules
- **Protected Actions (Requires Auth):** Actions involving personal, financial, or order data (e.g. tracking specific orders, updating profile details, viewing order lists) require an authenticated state.
- **Public Actions (No Auth Required):** Generic questions (FAQ, policy lookups, company info, product catalogs) do not require authentication and can be answered freely for both Guests and Users.

## 3. Orchestration & Error Handling Policy
- **For Guests (No Token):**
  - If a Guest attempts a **Protected Action**, the pipeline must **NOT** execute the backend API tool. It must immediately return the unauthenticated template response (`RT_ERROR_UNAUTHENTICATED`) directing the user to sign in.
  - No human escalation ticket should be created.
- **For Authenticated Users (Token Supplied):**
  - The pipeline must propagate the token to the backend API tool.
  - If the backend API call returns a authorization error (`401`/`403` status), it must be classified as a security anomaly (`ErrorGroup.AUTH_ERROR_SENSITIVE`).
  - The system must immediately create an escalation ticket via the support queue (`escalated = True`) and render the critical support template (`RT_ESCALATE_GENERIC`).
