# [PROJECT NAME] - [SHORT PROJECT DESCRIPTION]

## Summary

FIXME: Provide a concise overview of the project, its purpose, the problem it addresses, and its main objectives.

<details>
<summary><b>Table of Contents (Click to expand)</b></summary>

- [Summary](#summary)
- [How to install and run](#how-to-install-and-run)
  - [Prerequisites](#prerequisites)
  - [Configuring and running](#configuring-and-running)
    - [Installing Docker on your OS](#installing-docker-on-your-os)
      - [Windows 10](#windows-10)
      - [Windows Subsystem for Linux (WSL / WSL 2)](#windows-subsystem-for-linux-wsl--wsl-2)
      - [Debian-based Linux (Ubuntu, Debian, Mint)](#debian-based-linux-ubuntu-debian-mint)
      - [Arch-based Linux (Arch Linux, Manjaro)](#arch-based-linux-arch-linux-manjaro)
    - [Step 0: Retrieving project files](#step-0-retrieving-project-files)
    - [Step 1: Environment Configuration (one-shot)](#step-1-environment-configuration-one-shot)
      - [WARNING about CRITICAL CONFIGURATION VALUES](#warning-about-critical-configuration-values)
      - [Database Initialization Modes (`INIT_MODE`)](#database-initialization-modes-init_mode)
    - [Switching Database Seeding Modes (`demo` ↔ `minimal`)](#switching-database-seeding-modes-demo--minimal)
    - [Step 2: Manually managing the application (repeatable)](#step-2-manually-managing-the-application-repeatable)
      - [Starting](#starting)
        - [Automatically](#automatically)
        - [Manually (for finer control)](#manually-for-finer-control)
      - [Monitoring](#monitoring)
      - [Stopping](#stopping)
      - [Deleting all information (containers AND database)](#deleting-all-information-containers-and-database)
- [How to use](#how-to-use)
  - [Starting / stopping program](#starting--stopping-program)
  - [Usage overview](#usage-overview)
- [Features and limitations](#features-and-limitations)
  - [Supported (v1.0)](#supported-v10)
    - [Multi-Branch & Inventory Core Management](#multi-branch--inventory-core-management)
    - [Real-Time Synchronization (Server-Sent Events)](#real-time-synchronization-server-sent-events)
    - [Security & Role-Based Access Control (RBAC)](#security--role-based-access-control-rbac)
    - [AI Assistant & Model Context Protocol (MCP) Integration](#ai-assistant--model-context-protocol-mcp-integration)
    - [Containerized Architecture & Portability](#containerized-architecture--portability)
  - [Not Supported (yet) & Known Limitations](#not-supported-yet--known-limitations)
    - [AI Assistant & MCP Integration](#ai-assistant--mcp-integration)
    - [Architecture & Real-Time Engine](#architecture--real-time-engine)
    - [Security & Production Readiness](#security--production-readiness)
    - [Testing & Code Coverage](#testing--code-coverage)
- [Examples of use](#examples-of-use)
  - [Valid examples](#valid-examples)
    - [Getting information on a specific product (per id or sku) in various languages](#getting-information-on-a-specific-product-per-id-or-sku-in-various-languages)
    - [Questions about stocks for a product or a branch](#questions-about-stocks-for-a-product-or-a-branch)
    - [Mixed questions](#mixed-questions)
  - [Failing examples](#failing-examples)
- [Technical information](#technical-information)
  - [General architecture](#general-architecture)
    - [Core design principles](#core-design-principles)
    - [Main code structuration](#main-code-structuration)
  - [Technical stack overview](#technical-stack-overview)
  - [Communications overview](#communications-overview)
  - [Process Flow for a request from end-user](#process-flow-for-a-request-from-end-user)
    - [Backoffice...](#backoffice)
    - [Frontoffice](#frontoffice)
  - [Architecture macro diagram](#architecture-macro-diagram)
  - [Memory management & Performance](#memory-management--performance)
- [Testing](#testing)
- [Project constraints and methodology](#project-constraints-and-methodology)
  - [Imposed constraints](#imposed-constraints)
    - [Requirements](#requirements)
  - [Project methodology](#project-methodology)
  - [Acknowledgments](#acknowledgments)
- [Technologies Used](#technologies-used)
- [Authors](#authors)
- [License](#license)

</details>

## How to install and run

<details>
<summary>(Click for detailed information on prerequisites, download and installation/configuration/run steps)</summary>

### Prerequisites

FIXME: List all requirements needed to run the project, distinguishing mandatory system requirements from optional requirements needed for development, testing, or running individual components.

FIXME: Mention required software, runtimes, package managers, accounts, hardware, network access, external services, and other prerequisites.

#### Additional Requirements:

FIXME: List additional tools or software that are useful or required for specific workflows, such as Git, a web browser, development tools, or testing dependencies.

#### Installing Docker on your OS

FIXME: Explain how Docker or the main container/runtime environment can be installed when relevant.

##### Windows 10

FIXME: Provide installation instructions specific to this operating system/version.

##### Windows Subsystem for Linux (WSL / WSL 2)

FIXME: Provide installation and integration instructions specific to WSL/WSL 2.

##### Debian-based Linux (Ubuntu, Debian, Mint)

FIXME: Provide installation instructions for Debian-based distributions.

##### Arch-based Linux (Arch Linux, Manjaro)

FIXME: Provide installation instructions for Arch-based distributions.

### Configuring and running

FIXME: Explain the overall configuration and startup process, including how configuration is provided and where configuration files are expected.

#### Step 0: Retrieving project files

FIXME: Explain how to clone, download, or otherwise obtain the project files.

#### Step 1: Environment Configuration (one-shot)

FIXME: Explain how to create and configure the project's environment/configuration file(s).

##### WARNING about CRITICAL CONFIGURATION VALUES

FIXME: Clearly identify secrets, passwords, API keys, tokens, URLs, or other values that must be changed before running the project.

FIXME: Explain how users should generate secure values where applicable.

##### Database Initialization Modes (`INIT_MODE`)

FIXME: Document available database initialization/seeding modes, their purpose, defaults, and configuration variables.

#### Switching Database Seeding Modes (`demo` ↔ `minimal`)

FIXME: Explain how to switch between initialization/seeding modes and whether existing persistent data must be removed first.

#### Step 2: Manually managing the application (repeatable)

FIXME: Explain the commands and procedures that can be repeatedly used to manage the application after initial configuration.

##### Starting

FIXME: Explain how to start/build the complete application stack.

###### Automatically

FIXME: Document the recommended/simple startup method, such as a project-provided script.

###### Manually (for finer control)

FIXME: Document the manual commands for users who need more control over the build or startup process.

FIXME: Explain relevant command-line options and their effects.

##### Monitoring

FIXME: Explain how to inspect service status, logs, resource usage, health, and other runtime information.

##### Stopping

FIXME: Explain how to stop the application while preserving persistent data.

##### Deleting all information (containers AND database)

FIXME: Explain how to completely remove containers, volumes, generated data, downloaded models, or other persistent resources.

FIXME: Clearly warn the user about irreversible data loss.

</details>

## How to use

### Starting / stopping program

FIXME: Provide the shortest practical instructions for starting and stopping the application once all installation and configuration steps have been completed.

FIXME: Document default access URLs, ports, credentials, or other information needed to access the running application.

### Usage overview

FIXME: Explain the main user workflows and how the major application components are used.

FIXME: Describe the interaction between the main user-facing interfaces/components.

<details><summary>Client UI sneak peek</summary>
<p align="center">
  <img src="[PATH TO SCREENSHOT]"
       alt="[DESCRIPTION OF SCREENSHOT]"
       width="800">
</p>
</details>

FIXME: Optionally provide screenshots or other visual examples of the main user interface.

<details><summary>Backoffice UI sneak peek</summary>
<p align="center">
  <img src="[PATH TO ADMIN SCREENSHOT]" alt="[DESCRIPTION]" width="48%">
  <img src="[PATH TO MANAGER SCREENSHOT]" alt="[DESCRIPTION]" width="48%">
</p>
</details>

FIXME: Describe any important user-interface-specific behavior, restrictions, or workflows.

## Features and limitations

FIXME: Briefly explain the overall scope of the project and whether the current version should be considered a proof-of-concept, prototype, MVP, production-ready system, etc.

### Supported (v1.0)

FIXME: Provide a high-level list of the features available in the current release.

#### Multi-Branch & Inventory Core Management

FIXME: Describe inventory, catalog, branch, stock, CRUD, validation, synchronization, or other core business functionality.

#### Real-Time Synchronization (Server-Sent Events)

FIXME: Describe real-time update mechanisms, event propagation, affected interfaces, and any relevant implementation details.

#### Security & Role-Based Access Control (RBAC)

FIXME: Describe authentication, authorization, roles, permissions, session/token handling, and inter-service security.

#### AI Assistant & Model Context Protocol (MCP) Integration

FIXME: Describe AI-assisted functionality, supported interactions, MCP tools/resources, model/provider support, and how AI interacts with application data.

#### Containerized Architecture & Portability

FIXME: Describe containerization, orchestration, portability, persistence, deployment characteristics, and relevant infrastructure features.

### Not Supported (yet) & Known Limitations

FIXME: Explain the project's current limitations and deliberate trade-offs.

#### AI Assistant & MCP Integration

FIXME: Document limitations related to AI behavior, context/memory, supported languages, model quality, tool calling, data enrichment, latency, or provider-specific behavior.

#### Architecture & Real-Time Engine

FIXME: Document architectural limitations such as scaling constraints, single-node assumptions, resource requirements, or infrastructure dependencies.

#### Security & Production Readiness

FIXME: Document known security limitations, missing hardening, missing audits, network-security concerns, rate limiting, CORS, authentication limitations, or other production-readiness concerns.

#### Testing & Code Coverage

FIXME: Document missing automated tests, incomplete coverage, unsupported testing layers, and known testing limitations.

## Examples of use

<details>
<summary>(Click to expand)</summary>

### Valid examples

FIXME: Provide representative successful use cases demonstrating the main capabilities of the application.

#### Getting information on a specific product (per id or sku) in various languages

FIXME: Provide examples of queries/inputs using the most common identifiers and, where relevant, different supported languages.

FIXME: Show representative expected outputs.

#### Questions about stocks for a product or a branch

FIXME: Provide examples involving stock availability, branches, quantities, or inventory aggregation.

FIXME: Show representative expected outputs.

#### Mixed questions

FIXME: Provide examples combining multiple supported capabilities in a single request.

### Failing examples

FIXME: Provide representative unsupported, invalid, ambiguous, or out-of-scope requests.

FIXME: Explain the expected failure/refusal/error behavior.

</details>

## Technical information

FIXME: State the intended scope of this section and link to a deeper architecture/technical document if one exists.

### General architecture

FIXME: Provide a high-level description of the system architecture and the responsibilities of its major components.

#### Core design principles

FIXME: Explain the architectural principles, design decisions, separation of concerns, security boundaries, maintainability goals, or other principles guiding the implementation.

#### Main code structuration

FIXME: Describe the main application components, services, modules, packages, or layers and their respective responsibilities.

### Technical stack overview

FIXME: Summarize the main programming languages, frameworks, libraries, databases, infrastructure, and external services used to implement the project.

### Communications overview

FIXME: Describe how the major components communicate with each other, including protocols, APIs, authentication mechanisms, data formats, and relevant communication constraints.

```mermaid
FIXME: Replace this with a high-level architecture/communication diagram if useful.
```

Backoffice...

FIXME: Describe the internal-user flow, including authentication, interface actions, API calls, business operations, and responses.

Frontoffice

FIXME: Describe the anonymous/end-user flow, including input handling, communication with backend/AI services, context retrieval, and response generation.

### Architecture macro diagram

FIXME: Provide a high-level architecture diagram showing the major components and their relationships.

<p align="center"> <img src="[PATH TO ARCHITECTURE DIAGRAM]" alt="[DESCRIPTION OF ARCHITECTURE DIAGRAM]" width="600"> </p>


### Memory management & Performance

FIXME give hindsight on how much memory is expected to be consumed, with example metrics if possible.

## Testing

FIXME make short summary, delegate to TESTING.md

## Project constraints and methodology

### Imposed constraints

This project has been realized in compliance with all business specifications and technical constraints detailed in the [Project context](./PROJECT.md)

#### Requirements

Confer `PROJECT.md`

### Project methodology

FIXME short summary explaining how we worked (branching, planning, reviews etc)

### Acknowledgments


## Technologies Used

FIXME put listing of "badges" for technos.

## Authors

FIXME list authors with links to githubs

## License

FIXME license
