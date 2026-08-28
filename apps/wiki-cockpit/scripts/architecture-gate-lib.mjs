import fs from "node:fs";
import path from "node:path";
import ts from "typescript";

export const ARCHITECTURE_POLICY_VERSION = "wiki-viva-cockpit.boundaries.v2";

const ROUTER_MUTATION_SYMBOLS = new Set([
  "installLinkInterceptor",
  "navigate",
  "patchWorld",
  "retreat"
]);

const UI_ENGINE_PACKAGES = new Set([
  "react",
  "react-dom",
  "react-dom/client",
  "lucide-react",
  "three",
  "three-stdlib",
  "@react-three/fiber",
  "@react-three/drei"
]);

const SOURCE_EXTENSIONS = new Set([".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"]);
const RESOLUTION_EXTENSIONS = ["", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs"];
const TRANSPORT_PACKAGES = new Set([
  "axios",
  "ky",
  "fs",
  "http",
  "https",
  "node:fs",
  "node:http",
  "node:https",
  "node:net",
  "node:tls"
]);

function toPosix(value) {
  return value.split(path.sep).join("/");
}

function isProductionSource(file) {
  return (
    SOURCE_EXTENSIONS.has(path.extname(file)) &&
    !/\.(?:test|spec|stories)\.[cm]?[jt]sx?$/.test(file) &&
    !file.endsWith(".d.ts")
  );
}

function walk(root) {
  if (!fs.existsSync(root)) return [];
  const files = [];
  const pending = [root];
  while (pending.length) {
    const current = pending.pop();
    for (const entry of fs.readdirSync(current, { withFileTypes: true })) {
      const absolute = path.join(current, entry.name);
      if (entry.isDirectory()) pending.push(absolute);
      else if (entry.isFile() && isProductionSource(absolute)) files.push(absolute);
    }
  }
  return files.sort();
}

function lineFor(sourceFile, position) {
  return sourceFile.getLineAndCharacterOfPosition(position).line + 1;
}

function importSymbols(clause) {
  if (!clause) return [];
  const declarationTypeOnly = Boolean(clause.isTypeOnly);
  const symbols = [];
  if (clause.name) symbols.push({ name: "default", typeOnly: declarationTypeOnly });
  if (clause.namedBindings && ts.isNamespaceImport(clause.namedBindings)) {
    symbols.push({ name: "*", typeOnly: declarationTypeOnly });
  }
  if (clause.namedBindings && ts.isNamedImports(clause.namedBindings)) {
    for (const element of clause.namedBindings.elements) {
      symbols.push({
        name: (element.propertyName ?? element.name).text,
        typeOnly: declarationTypeOnly || element.isTypeOnly
      });
    }
  }
  return symbols;
}

function parseDependencies(sourceFile) {
  const dependencies = [];
  const visit = (node) => {
    if (ts.isImportDeclaration(node) && ts.isStringLiteral(node.moduleSpecifier)) {
      const symbols = importSymbols(node.importClause);
      dependencies.push({
        kind: "import",
        specifier: node.moduleSpecifier.text,
        symbols: symbols.length ? symbols : [{ name: "side-effect", typeOnly: false }],
        line: lineFor(sourceFile, node.getStart(sourceFile))
      });
    } else if (ts.isExportDeclaration(node) && node.moduleSpecifier && ts.isStringLiteral(node.moduleSpecifier)) {
      const typeOnly = Boolean(node.isTypeOnly);
      const symbols = node.exportClause && ts.isNamedExports(node.exportClause)
        ? node.exportClause.elements.map((element) => ({
            name: (element.propertyName ?? element.name).text,
            typeOnly: typeOnly || element.isTypeOnly
          }))
        : [{ name: "*", typeOnly }];
      dependencies.push({
        kind: "export",
        specifier: node.moduleSpecifier.text,
        symbols,
        line: lineFor(sourceFile, node.getStart(sourceFile))
      });
    } else if (
      ts.isCallExpression(node) &&
      node.expression.kind === ts.SyntaxKind.ImportKeyword &&
      node.arguments.length === 1 &&
      ts.isStringLiteral(node.arguments[0])
    ) {
      dependencies.push({
        kind: "dynamic-import",
        specifier: node.arguments[0].text,
        symbols: [{ name: "*", typeOnly: false }],
        line: lineFor(sourceFile, node.getStart(sourceFile))
      });
    }
    ts.forEachChild(node, visit);
  };
  visit(sourceFile);
  return dependencies;
}

function resolveDependency(fromFile, specifier, appRoot) {
  if (!specifier.startsWith(".")) return null;
  const unresolved = path.resolve(path.dirname(fromFile), specifier);
  const candidates = [];
  for (const extension of RESOLUTION_EXTENSIONS) candidates.push(`${unresolved}${extension}`);
  for (const extension of RESOLUTION_EXTENSIONS.slice(1)) candidates.push(path.join(unresolved, `index${extension}`));
  const resolved = candidates.find((candidate) => fs.existsSync(candidate) && fs.statSync(candidate).isFile());
  return resolved ? toPosix(path.relative(appRoot, resolved)) : toPosix(path.relative(appRoot, unresolved));
}

function isComponent(file) {
  return file === "src/App.tsx" || file.startsWith("src/components/");
}

function isSystem(file) {
  return file.startsWith("src/scene/") || file.startsWith("src/world/systems/");
}

function isClient(file) {
  return file === "src/data/snapshot.ts" || file.startsWith("src/world/clients/");
}

function isState(file) {
  return file.startsWith("src/world/state/");
}

function isEffect(file) {
  return file.startsWith("src/world/effects/");
}

function isRouterTarget(target) {
  return target === "src/router.ts" || target === "src/router";
}

function isTransportTarget(target) {
  return target === "src/data/snapshot.ts" || target?.startsWith("src/world/clients/");
}

function isUiSurfaceTarget(target) {
  return target === "src/App.tsx" || target?.startsWith("src/components/");
}

function isSceneTarget(target) {
  return target?.startsWith("src/scene/") || target?.startsWith("src/world/systems/");
}

function isUiEnginePackage(specifier) {
  return (
    UI_ENGINE_PACKAGES.has(specifier) ||
    specifier.startsWith("@react-three/") ||
    specifier.startsWith("react/") ||
    specifier.startsWith("react-dom/") ||
    specifier.startsWith("three/")
  );
}

function isTransportPackage(specifier) {
  return TRANSPORT_PACKAGES.has(specifier);
}

function dependencyEvidence(dependency, symbol) {
  return `${dependency.kind}:${dependency.specifier}:${symbol}`;
}

function isRuntimeDependency(dependency) {
  return dependency.symbols.some((symbol) => !symbol.typeOnly);
}

function transitiveCapabilityPaths(records, seed, kind) {
  const paths = new Map();
  for (const record of records) {
    if (seed(record)) paths.set(record.file, [record.file]);
  }
  let changed = true;
  while (changed) {
    changed = false;
    for (const record of records) {
      if (paths.has(record.file)) continue;
      const dependency = record.dependencies.find(
        (entry) => isRuntimeDependency(entry) && entry.target && paths.has(entry.target)
      );
      if (!dependency) continue;
      paths.set(record.file, [record.file, ...paths.get(dependency.target)]);
      changed = true;
    }
  }
  return { kind, paths };
}

function addTransitiveComponentViolations(violations, records) {
  const transport = transitiveCapabilityPaths(
    records,
    (record) =>
      isClient(record.file) ||
      record.dependencies.some((entry) => isRuntimeDependency(entry) && isTransportPackage(entry.specifier)) ||
      directTransportCapabilities(record.sourceFile).length > 0,
    "transport"
  );
  const routeMutation = transitiveCapabilityPaths(
    records,
    (record) =>
      directHistoryCalls(record.sourceFile).length > 0 ||
      record.dependencies.some(
        (entry) =>
          isRuntimeDependency(entry) &&
          isRouterTarget(entry.target) &&
          entry.symbols.some((symbol) => !symbol.typeOnly && (ROUTER_MUTATION_SYMBOLS.has(symbol.name) || symbol.name === "*"))
      ),
    "router mutation"
  );

  for (const record of records.filter((entry) => isComponent(entry.file))) {
    for (const capability of [transport, routeMutation]) {
      const path = capability.paths.get(record.file);
      // Direct imports/calls already have precise first-order rules. This rule
      // is deliberately about facades two or more edges deep.
      if (!path || path.length < 2) continue;
      if (
        path.length === 2 &&
        (capability.kind === "transport" ? isTransportTarget(path[1]) : isRouterTarget(path[1]))
      ) continue;
      const firstHop = record.dependencies.find(
        (entry) => isRuntimeDependency(entry) && entry.target === path[1]
      );
      const ruleId = capability.kind === "transport"
        ? "components-no-transitive-transport"
        : "components-no-transitive-router-mutation";
      violations.push(
        violation(
          ruleId,
          record.file,
          `path:${path.join("->")}`,
          `Component reaches ${capability.kind} capability transitively through ${path.slice(1).join(" -> ")}; inject a typed port from the composition root instead.`,
          firstHop?.line ?? 1
        )
      );
    }
  }
}

function propertyChain(node) {
  if (ts.isIdentifier(node)) return node.text;
  if (ts.isPropertyAccessExpression(node)) {
    const parent = propertyChain(node.expression);
    return parent ? `${parent}.${node.name.text}` : node.name.text;
  }
  return "";
}

function directHistoryCalls(sourceFile) {
  const calls = [];
  const allowedMethods = new Set(["pushState", "replaceState", "back", "forward", "go"]);
  const visit = (node) => {
    if (ts.isCallExpression(node)) {
      const chain = propertyChain(node.expression);
      const parts = chain.split(".");
      const method = parts.at(-1);
      const historyRoot = parts.slice(0, -1).join(".");
      if (allowedMethods.has(method) && (historyRoot === "history" || historyRoot === "window.history")) {
        calls.push({ method, line: lineFor(sourceFile, node.getStart(sourceFile)) });
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(sourceFile);
  return calls;
}

function forbiddenStateCapabilities(sourceFile) {
  const forbidden = new Set([
    "fetch",
    "XMLHttpRequest",
    "WebSocket",
    "EventSource",
    "Worker",
    "SharedWorker",
    "BroadcastChannel",
    "document",
    "window",
    "navigator",
    "localStorage",
    "sessionStorage",
    "indexedDB"
  ]);
  const found = new Map();
  const visit = (node) => {
    if (ts.isIdentifier(node) && forbidden.has(node.text) && !found.has(node.text)) {
      found.set(node.text, lineFor(sourceFile, node.getStart(sourceFile)));
    }
    ts.forEachChild(node, visit);
  };
  visit(sourceFile);
  return [...found].map(([capability, line]) => ({ capability, line }));
}

function directTransportCapabilities(sourceFile) {
  const forbidden = new Set(["fetch", "XMLHttpRequest", "WebSocket", "EventSource"]);
  const found = new Map();
  const visit = (node) => {
    if (ts.isIdentifier(node) && forbidden.has(node.text) && !found.has(node.text)) {
      found.set(node.text, lineFor(sourceFile, node.getStart(sourceFile)));
    }
    ts.forEachChild(node, visit);
  };
  visit(sourceFile);
  return [...found].map(([capability, line]) => ({ capability, line }));
}

function untrustedEffectGenerators(sourceFile) {
  const found = [];
  const visit = (node) => {
    if (ts.isCallExpression(node)) {
      const chain = propertyChain(node.expression);
      if (chain === "Math.random" || chain === "crypto.randomUUID") {
        found.push({ generator: chain, line: lineFor(sourceFile, node.getStart(sourceFile)) });
      }
    }
    ts.forEachChild(node, visit);
  };
  visit(sourceFile);
  return found;
}

function violation(ruleId, file, evidence, detail, line) {
  return { ruleId, file, evidence, detail, line };
}

function addImportViolation(violations, ruleId, file, dependency, symbol, detail) {
  violations.push(violation(ruleId, file, dependencyEvidence(dependency, symbol), detail, dependency.line));
}

export function fingerprintViolation(entry) {
  return `${entry.ruleId}|${entry.file}|${entry.evidence}`;
}

function assignStableOrdinals(violations) {
  const counts = new Map();
  return violations
    .sort((left, right) =>
      left.file.localeCompare(right.file) ||
      left.ruleId.localeCompare(right.ruleId) ||
      left.evidence.localeCompare(right.evidence) ||
      left.line - right.line
    )
    .map((entry) => {
      const base = fingerprintViolation(entry);
      const ordinal = (counts.get(base) ?? 0) + 1;
      counts.set(base, ordinal);
      return { ...entry, fingerprint: `${base}|${ordinal}` };
    });
}

export function collectArchitectureViolations(appRoot) {
  const sourceRoot = path.join(appRoot, "src");
  const violations = [];
  const records = walk(sourceRoot).map((absoluteFile) => {
    const file = toPosix(path.relative(appRoot, absoluteFile));
    const sourceText = fs.readFileSync(absoluteFile, "utf8");
    const sourceFile = ts.createSourceFile(
      absoluteFile,
      sourceText,
      ts.ScriptTarget.Latest,
      true,
      absoluteFile.endsWith("x") ? ts.ScriptKind.TSX : ts.ScriptKind.TS
    );
    const dependencies = parseDependencies(sourceFile).map((dependency) => ({
      ...dependency,
      target: resolveDependency(absoluteFile, dependency.specifier, appRoot)
    }));
    return { absoluteFile, file, sourceFile, dependencies };
  });

  for (const { file, sourceFile, dependencies } of records) {

    if (isComponent(file)) {
      for (const dependency of dependencies) {
        if (isTransportTarget(dependency.target) || isTransportPackage(dependency.specifier)) {
          addImportViolation(
            violations,
            "components-no-transport",
            file,
            dependency,
            "*",
            "Components dispatch registered events; transport clients belong behind runtime resources/effects."
          );
        }
        if (isRouterTarget(dependency.target)) {
          for (const symbol of dependency.symbols.filter((entry) => !entry.typeOnly)) {
            if (ROUTER_MUTATION_SYMBOLS.has(symbol.name) || symbol.name === "*") {
              addImportViolation(
                violations,
                "components-no-router-mutation",
                file,
                dependency,
                symbol.name,
                `Component imports semantic router helper '${symbol.name}' instead of dispatching a runtime event.`
              );
            }
          }
        }
      }
      for (const call of directHistoryCalls(sourceFile)) {
        violations.push(
          violation(
            "components-no-direct-history",
            file,
            `call:${call.method}`,
            `Component calls history.${call.method} directly instead of dispatching a runtime interaction.`,
            call.line
          )
        );
      }
      for (const item of directTransportCapabilities(sourceFile)) {
        violations.push(
          violation(
            "components-no-transport",
            file,
            `capability:${item.capability}`,
            `Component uses transport capability '${item.capability}' directly instead of a runtime resource/effect.`,
            item.line
          )
        );
      }
    }

    if (isSystem(file)) {
      for (const dependency of dependencies) {
        if (isUiEnginePackage(dependency.specifier) || isUiSurfaceTarget(dependency.target)) {
          addImportViolation(
            violations,
            "systems-are-renderer-pure",
            file,
            dependency,
            "*",
            "Scene systems return render instructions and cannot depend on React/Three render surfaces."
          );
        }
        if (isTransportTarget(dependency.target) || isTransportPackage(dependency.specifier)) {
          addImportViolation(
            violations,
            "systems-no-operator-clients",
            file,
            dependency,
            "*",
            "Scene systems cannot import snapshot/operator transport clients."
          );
        }
        if (isRouterTarget(dependency.target)) {
          for (const symbol of dependency.symbols.filter((entry) => !entry.typeOnly)) {
            if (ROUTER_MUTATION_SYMBOLS.has(symbol.name) || symbol.name === "*") {
              addImportViolation(
                violations,
                "systems-no-route-writers",
                file,
                dependency,
                symbol.name,
                "Scene systems cannot write semantic route state."
              );
            }
          }
        }
      }
      for (const item of directTransportCapabilities(sourceFile)) {
        violations.push(
          violation(
            "systems-no-operator-clients",
            file,
            `capability:${item.capability}`,
            `Scene system uses transport capability '${item.capability}' directly.`,
            item.line
          )
        );
      }
    }

    if (isClient(file)) {
      for (const dependency of dependencies) {
        if (isUiEnginePackage(dependency.specifier) || isUiSurfaceTarget(dependency.target) || isSceneTarget(dependency.target)) {
          addImportViolation(
            violations,
            "clients-no-ui-engine",
            file,
            dependency,
            "*",
            "Clients own transport/schema validation and cannot depend on React or Three.js surfaces."
          );
        }
      }
    }

    if (isState(file)) {
      for (const dependency of dependencies) {
        if (
          isTransportTarget(dependency.target) ||
          isUiSurfaceTarget(dependency.target) ||
          isSceneTarget(dependency.target) ||
          dependency.target?.startsWith("src/world/effects/") ||
          isUiEnginePackage(dependency.specifier) ||
          isTransportPackage(dependency.specifier)
        ) {
          addImportViolation(
            violations,
            "state-is-pure",
            file,
            dependency,
            "*",
            "State/reducers cannot perform I/O or depend on DOM, effects, React or Three.js."
          );
        }
      }
      for (const item of forbiddenStateCapabilities(sourceFile)) {
        violations.push(
          violation(
            "state-is-pure",
            file,
            `capability:${item.capability}`,
            `State/reducer reads forbidden runtime capability '${item.capability}'.`,
            item.line
          )
        );
      }
    }

    if (isEffect(file)) {
      for (const dependency of dependencies) {
        if (isUiSurfaceTarget(dependency.target) || isSceneTarget(dependency.target)) {
          addImportViolation(
            violations,
            "effects-no-ui-coupling",
            file,
            dependency,
            "*",
            "Effects execute declared work and cannot depend on visual surfaces or scene systems."
          );
        }
      }
      for (const item of untrustedEffectGenerators(sourceFile)) {
        violations.push(
          violation(
            "effects-no-invented-semantics",
            file,
            `generator:${item.generator}`,
            `Effect uses '${item.generator}'; semantic IDs/data must come from snapshot inputs or command receipts.`,
            item.line
          )
        );
      }
    }

    if (
      file.startsWith("src/world/") &&
      file !== "src/world/state/routeHydration.ts"
    ) {
      for (const dependency of dependencies.filter((entry) => isRouterTarget(entry.target))) {
        addImportViolation(
          violations,
          "world-core-no-legacy-router",
          file,
          dependency,
          "*",
          "Canonical world contracts/runtime cannot depend on the legacy router compatibility module."
        );
      }
    }
  }

  addTransitiveComponentViolations(violations, records);

  return assignStableOrdinals(violations);
}

export function evaluateArchitectureBaseline(violations, baseline) {
  const baselineErrors = [];
  if (baseline?.policyVersion !== ARCHITECTURE_POLICY_VERSION) {
    baselineErrors.push(
      `Baseline policyVersion must be '${ARCHITECTURE_POLICY_VERSION}', got '${baseline?.policyVersion ?? "missing"}'.`
    );
  }
  if (!Array.isArray(baseline?.debt)) baselineErrors.push("Baseline must contain a debt array.");

  const debt = Array.isArray(baseline?.debt) ? baseline.debt : [];
  if (debt.length > 0) {
    baselineErrors.push("The v2 boundary policy is zero-debt; architecture baseline growth is not permitted.");
  }
  const baselineByFingerprint = new Map();
  const normalizedDebt = [];
  for (const rawEntry of debt) {
    const fingerprint = typeof rawEntry === "string" ? rawEntry : rawEntry?.fingerprint;
    const ruleId = typeof fingerprint === "string" ? fingerprint.split("|", 1)[0] : "";
    const sharedMetadata = baseline?.ruleDebt?.[ruleId];
    const entry = typeof rawEntry === "string"
      ? { fingerprint, reason: sharedMetadata?.reason, removal: sharedMetadata?.removal }
      : rawEntry;
    if (!entry || typeof entry.fingerprint !== "string" || !entry.fingerprint) {
      baselineErrors.push("Every debt entry needs a non-empty fingerprint.");
      continue;
    }
    if (baselineByFingerprint.has(entry.fingerprint)) {
      baselineErrors.push(`Duplicate debt fingerprint: ${entry.fingerprint}`);
      continue;
    }
    if (typeof entry.reason !== "string" || !entry.reason.trim()) {
      baselineErrors.push(`Debt '${entry.fingerprint}' needs a reason.`);
    }
    if (typeof entry.removal !== "string" || !entry.removal.trim()) {
      baselineErrors.push(`Debt '${entry.fingerprint}' needs a removal condition.`);
    }
    baselineByFingerprint.set(entry.fingerprint, entry);
    normalizedDebt.push(entry);
  }

  const currentByFingerprint = new Map(violations.map((entry) => [entry.fingerprint, entry]));
  const regressions = violations.filter((entry) => !baselineByFingerprint.has(entry.fingerprint));
  const staleDebt = normalizedDebt.filter((entry) => !currentByFingerprint.has(entry.fingerprint));

  return {
    ok: baselineErrors.length === 0 && regressions.length === 0 && staleDebt.length === 0,
    baselineErrors,
    regressions,
    staleDebt,
    acceptedDebt: violations.filter((entry) => baselineByFingerprint.has(entry.fingerprint))
  };
}

export function readArchitectureBaseline(file) {
  return JSON.parse(fs.readFileSync(file, "utf8"));
}

export function summarizeByRule(violations) {
  const counts = new Map();
  for (const entry of violations) counts.set(entry.ruleId, (counts.get(entry.ruleId) ?? 0) + 1);
  return [...counts].sort(([left], [right]) => left.localeCompare(right));
}
