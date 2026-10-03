# Generative UI Workspace on an Infinite Canvas

**Product requirements document — vision draft**  
**Version:** 0.1  
**Date:** 2 October 2026  
**Product owner:** Gokul Krishnan  
**Status:** Product vision captured; implementation approach to be defined later.

## 1. Product vision

Enable users to create, explore, and maintain multiple dashboards in one persistent infinite canvas by expressing what they want in natural language.

The product understands the business meaning of database tables and columns through a reviewed metadata wrapper. An agent uses that understanding to define data requests and generate UI descriptions. The application executes those requests and renders the actual results directly into the interface. Business records and query results do not pass through the agent.

Users should be able to ask for a dashboard, select part of it, request a change, and keep working without waiting for a developer to build a new dashboard for each requirement.

## 2. Problem

Teams repeatedly build dashboards to display different combinations of data from the same databases. New columns, filters, joins, metrics, and presentation formats can create further development work. Fixed dashboard layouts also make it difficult for users to keep several related views together.

Natural-language interaction alone does not address this problem if every answer is temporary, users must manually configure everything, or an agent must receive the underlying business data.

The product needs a reusable understanding of the database, persistent visual workspaces, and a clear separation between generation and data execution.

## 3. Intended users

| User | Need |
| --- | --- |
| Business or operations user | Request and refine useful views without writing queries or building UI |
| Analyst or domain expert | Review business definitions and validate that generated views represent the intended metrics |
| Data owner or administrator | Connect approved data sources, review metadata, and control access |

These are initial user groups for discovery, rather than a finalized target market.

## 4. Core product principles

1. **Describe the need, receive a working view.** Users express business intent; the system handles query planning and presentation.
2. **Draft first, review where necessary.** Database onboarding starts with agent-generated metadata descriptions rather than a blank form.
3. **Keep business data outside the agent.** The agent receives approved metadata and configuration context. Results flow from the execution service to the UI.
4. **Make work persistent.** Dashboards remain available, with their definitions and positions, for later use and refinement.
5. **Make changes local and understandable.** Selection identifies which dashboard or widget a request affects.
6. **Separate appearance from data requirements.** A presentation change should reuse available results when they are sufficient.

## 5. Product experience

### 5.1 Assisted database onboarding

An administrator connects an approved database. The system reads schema metadata, including table and column names, types, keys, relationships, constraints, and existing descriptions.

The agent drafts a business metadata wrapper covering:

- What each table represents and what one row means.
- Column meanings, units, and known coded values.
- Relationships and their cardinality, where known.
- Business metrics and calculations supported by available documentation.
- Ambiguities and inferred interpretations requiring review.

A knowledgeable reviewer corrects or approves the draft. The review experience should focus attention on uncertainty rather than require every description to be written manually. Business meanings unsupported by metadata must remain unresolved until clarified; the system must not silently treat guesses as facts.

Approved metadata becomes the reusable context for dashboard generation. Schema changes should surface affected definitions for review. The discovery and maintenance mechanisms will be designed later.

### 5.2 Generate dashboards through conversation

A user asks, for example, “Create a sales dashboard showing monthly sales, top customers, and regional performance.”

The agent uses relevant approved metadata to define data requests, including required joins, filters, fields, and aggregations. It also produces a UI description for suitable charts, tables, metrics, and filters.

The application validates the requests, fetches authorized data, and renders the dashboard on the canvas. It asks a targeted clarification when an unresolved business definition materially affects correctness.

### 5.3 Keep multiple dashboards in a single view

The infinite canvas supports multiple persistent dashboards, each containing its own widgets. Users can view several dashboards together and arrange them to suit their work.

The intended experience includes moving and resizing dashboards, panning and zooming, and returning to saved work. Named dashboard frames and a navigation aid are proposed ways to keep a growing canvas usable; their exact interaction design remains open.

### 5.4 Refine through selection and requests

Users select a dashboard or widget and request changes in natural language. The current definition provides context, so users do not need to repeat the original request.

| Request | Expected behavior |
| --- | --- |
| “Add customer region to this table” | Update fields and any required relationship, fetch updated results, and render the extra column |
| “Change this to a bar chart” | Change presentation and reuse results if they support the requested format |
| “Group this by month” | Update the data aggregation and fetch revised results |
| “Show only pending orders” | Update the relevant filter and refresh the affected views |
| “Move this next to the sales dashboard” | Update canvas placement without fetching data |

Changes should preserve unrelated dashboards and widgets. If the target is unclear, the system should resolve that ambiguity before applying the change.

### 5.5 Refresh and execution feedback

Each dashboard or widget should be able to show loading, success, empty results, and failure states independently. A slow or failed request should not block the rest of the workspace.

Users should see when data was last refreshed and whether an execution is still running. Any agent statement about execution timing must be grounded in service-provided status or timing metadata.

Saved views should be refreshable without asking the agent to recreate their definitions. Ordinary supported interactions, such as changing an existing filter, should not inherently require a new generation step.

## 6. Defined state

The product must retain a defined configuration for each dashboard and widget. The exact state model and persistence technology are deferred.

| Scope | Conceptual state |
| --- | --- |
| Canvas | Dashboard membership, positions, sizes, viewport, and selection |
| Dashboard | Name, widget collection, layout, and shared filters |
| Widget | Display type, selected fields, data request, bindings, sorting, and local filters |
| Runtime | Execution status, results, errors, and last refresh time |

Persistent configuration and transient runtime data are distinct. The agent may use configuration context needed for a change, but business records—including records held in a client cache—must not be included in its context.

Filters and user-entered parameters may themselves contain sensitive business values. Their handling must be defined so selection context does not accidentally bypass the data boundary.

Version history and undo are proposed capabilities for recovering from unwanted generated changes. Shared-filter precedence and widget overrides remain design questions.

## 7. Functional requirements

| ID | Requirement |
| --- | --- |
| FR-01 | Discover schema metadata from approved connected data sources |
| FR-02 | Generate an editable draft of table, column, and relationship descriptions |
| FR-03 | Review and maintain approved metadata, with uncertainty made explicit |
| FR-04 | Generate data requests and UI descriptions from natural-language requests |
| FR-05 | Validate data requests and enforce permissions before execution |
| FR-06 | Bind actual query results to generated UI without sending those results to the agent |
| FR-07 | Support multiple dashboards within one persistent canvas |
| FR-08 | Support requests scoped to selected dashboards or widgets |
| FR-09 | Save dashboard and widget definitions for reopening and refresh |
| FR-10 | Refresh affected data when a change requires it, and reuse results when sufficient |
| FR-11 | Provide independent execution feedback for affected views |
| FR-12 | Surface unresolved business meaning rather than invent a definition |

## 8. Correctness, access, and reliability expectations

- Generated requests must respect available relationships and row grain to avoid unintended duplication or incorrect aggregates.
- Data authorization must be enforced by the execution layer for every request, including requests from saved dashboards.
- Only supported UI and data operations may execute. Unsupported requests should produce an actionable explanation.
- Execution services should provide bounded requests and useful errors without exposing business records through agent-facing diagnostic messages.
- Multiple visible dashboards should remain usable under concurrent loading. Fetch scheduling, caching, and resource limits will be determined later.
- Saved definitions should identify dependencies so metadata or schema changes can be assessed for compatibility.

## 9. Scope boundaries

The current vision covers dashboard creation, data retrieval, visual rendering, refinement, state, and persistence.

The following are not committed in this draft:

- Editing or deleting underlying business records. Dashboard configuration updates are in scope; business-data writes require a separate product decision.
- Agent analysis of returned records or causal explanations based on those records.
- Arbitrary generated executable component code.
- Collaboration, sharing, scheduled reports, alerts, or exports.
- A specific database, framework, agent library, hosting environment, or API protocol.

## 10. Implementation decisions deferred

GraphQL was discussed as a possible API approach. It remains a candidate, alongside REST or another interface. No API contract or implementation is selected by this PRD.

Decisions for the next design phase include:

1. How data requests are represented: SQL, a structured plan, or defined analytics operations.
2. How joins and business metrics are reviewed and validated.
3. Whether UI generation configures a component catalog or supports a broader UI grammar.
4. How configuration changes are applied, validated, versioned, and undone.
5. How dashboards load and refresh across a large canvas.
6. What persistent state and behavioral state each entity owns.
7. Which data sources and visualization types are supported first.
8. How sensitive filter values are handled while maintaining the agent boundary.
9. Whether users can eventually perform business-data updates.

## 11. Success criteria

Targets and baselines will be established during discovery. Initial measures should include:

| Measure | What it evaluates |
| --- | --- |
| Time from request to usable dashboard | Whether the product reduces dashboard delivery effort |
| First-attempt query and presentation correctness | Whether generated views answer the intended question |
| Metadata review effort | Whether assisted onboarding reduces manual setup |
| Successful refinement rate | Whether users can modify views without rebuilding them |
| Return and reuse of saved dashboards | Whether the persistent workspace supports ongoing work |
| Execution responsiveness with multiple dashboards | Whether the canvas remains practical as it grows |
| Agent data-boundary verification | Whether business records remain outside generation inputs and outputs |

## 12. Illustrative acceptance journey

1. An administrator connects a database and receives a draft metadata wrapper.
2. A reviewer confirms key relationships and corrects an ambiguous status definition.
3. A business user requests a dashboard containing a table and charts.
4. The application retrieves permitted data and renders the views without exposing returned records to the agent.
5. The user creates another dashboard, and both remain visible on the canvas.
6. The user selects a table and asks for an extra column; only the affected definition and data request change.
7. The user changes a chart format; existing results are reused when sufficient.
8. One view takes longer to load and displays its execution status while other views remain usable.
9. The user returns later and refreshes saved dashboards without regenerating their definitions.

This journey captures the intended product behavior. Technical architecture, delivery phases, and detailed acceptance tests will follow after the approach is agreed.
