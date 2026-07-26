# Getting a free Dataverse environment for Dynamics 365

Dynamics is the last connector with **no real-server coverage** — everything we assert
about it comes from our reading of Microsoft's documentation. A free developer
environment closes that, and unlike NetSuite, Infor and Epicor it needs no approval
queue.

Total time: about 20 minutes. Cost: nothing.

Run `python backend/scripts/dynamics_verify.py` at the end. It checks the two things
that can independently be wrong and tells you which one is.

---

## 1. Get the environment (5 min)

**Power Apps Developer Plan** — <https://powerapps.microsoft.com/developerplan/>

It gives up to three Dataverse developer environments, free and indefinitely.

Sign up with a **work or school account** — `hamad@soundsafe.ai` qualifies. Personal
addresses (gmail.com, outlook.com) are rejected; this is the most common way the
signup fails, and the error does not say so clearly.

> The **Microsoft 365 Developer Program** used to be the usual route for a free E5
> sandbox tenant. Microsoft restricted it in 2024 and it now generally requires a
> Visual Studio subscription, so the Developer Plan above is the route to use.

Once provisioned, find the environment URL in the Power Platform admin center
(<https://admin.powerplatform.microsoft.com> → **Environments**). It looks like:

```
https://org1a2b3c4d.crm.dynamics.com
```

**The connector wants the subdomain only** — `org1a2b3c4d`. It builds
`https://{environment}.api.crm.dynamics.com/api/data/v9.2/` itself, so passing the full
URL produces a doubled host. `dynamics_verify.py` rejects a URL here rather than
failing later with something unreadable.

---

## 2. Register an app in Entra ID (5 min)

<https://portal.azure.com> → **Microsoft Entra ID** → **App registrations** → **New
registration**.

- Name: anything (`omniusgrid-dataverse`)
- Supported account types: **single tenant**
- Redirect URI: **leave blank** — the client-credentials grant has no redirect

Then note three values:

| Value | Where |
|---|---|
| **Tenant ID** | app registration → Overview → *Directory (tenant) ID* |
| **Client ID** | app registration → Overview → *Application (client) ID* |
| **Client secret** | **Certificates & secrets** → *New client secret* |

The secret is shown **once**. Copy it immediately; if you navigate away it cannot be
retrieved and you have to make another.

### Do NOT add API permissions

Counterintuitive, and worth stating plainly because most walkthroughs of the
*delegated* flow tell you to. Microsoft's own guidance for server-to-server:

> You don't need to grant the **Access Dynamics 365 as organization users** permission.
> This application is bound to a specific user account.

Adding that permission is harmless but does nothing, and — more importantly — it does
not substitute for step 3. Believing it does is how people get stuck.

---

## 3. Create the application user — the step that is actually load-bearing (5 min)

**Without this, you get a token successfully and every data request fails.** A token
only proves Entra ID trusts the app registration. Reading data additionally requires a
*Dataverse user* bound to that app, and the 401 you get without one says nothing about
application users.

<https://admin.powerplatform.microsoft.com> → **Environments** → your environment →
**Settings** → **Users + permissions** → **Application users** → **+ New app user**

1. **Add an app** → pick the app registration from step 2
2. Choose a **business unit** (the default is fine)
3. **Security roles** → assign one

For a developer environment, **System Administrator** is fine. For anything real, build
a least-privilege custom role instead.

An application user consumes **no paid licence**, so this is not a licensing decision.

---

## 4. Verify (1 min)

```bash
cd backend
export DATAVERSE_ORG='org1a2b3c4d'          # subdomain, not the URL
export DATAVERSE_TENANT_ID='<guid>'
export DATAVERSE_CLIENT_ID='<guid>'
export DATAVERSE_CLIENT_SECRET='<secret>'
python scripts/dynamics_verify.py
```

It runs two independent checks so a failure is attributable:

```
STEP 1  token from Entra ID     -> app registration + secret        (step 2 above)
STEP 2  WhoAmI with that token  -> Dataverse application user       (step 3 above)
```

`WhoAmI` is the right probe: any caller can invoke it, it needs no table privileges,
and it returns the `UserId` the token represents — precisely the fact in question.

Entra ID error codes are decoded rather than dumped. `AADSTS7000215` is a wrong or
expired secret, `AADSTS500011` usually means the org name is wrong or the environment
is in a different tenant, `AADSTS700016` means the client id is not registered here.

**If step 1 passes and step 2 fails, you skipped step 3.** The script says so.

---

## 5. What it unblocks

**Tier 4 — live Dynamics.** The last connector without real-server coverage gets some.

**Tier 2 — a spec-driven mock**, using the metadata routes:

```bash
export DATAVERSE_ORG_URL='https://org1a2b3c4d.crm.dynamics.com'
export DATAVERSE_BEARER_TOKEN='<token from step 1>'
./tools/erp-mocks/fetch-spec.sh dynamics
```

That pulls both schema forms, because they answer different questions:

- `$metadata` → CSDL/XML, the whole model, convertible to OpenAPI for Prism
- `EntityDefinitions` → JSON, queryable with `$select`/`$filter`/`$expand`

The second matters for the extraction layer: `EntitySetName` is **not** derivable from
`LogicalName`. `account` → `accounts` happens to pluralize; plenty do not, and guessing
produces a 404 that looks like an empty result.

Metadata queries are not paged — one request returns everything — so
`LabelLanguages=1033` is worth passing to keep the response from ballooning in a
multi-language environment.

---

## One thing already settled, so nobody re-litigates it

The connector requests the scope
`https://{org}.api.crm.dynamics.com/.default` — note the `.api.` infix. That looks
wrong, and it is not. Microsoft's own sample sets
`resource = "https://contoso.api.crm.dynamics.com"`, and the guidance states: *"For a
confidential client, use a scope of `<environment-url>/.default`."* `.default` is
required for client-credentials because Entra ID grants the app's configured
permissions rather than an ad-hoc scope list.
