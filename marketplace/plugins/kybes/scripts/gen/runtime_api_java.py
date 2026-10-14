"""Moduli comuni delle API Java (pacchetto <api>.generated): JSON, validatore, router e middleware, accesso ai dati,
adattatori per AWS Lambda, il server HTTP del JDK e Spring Boot (Web MVC funzionale).

Il nucleo usa solo il JDK: JSON e validazione sono scritti qui, con le stesse regole e gli stessi testi di Python e
TypeScript. __PKG__ è il pacchetto del codice API generato, __MGEN__ quello del modello generato.
"""
from __future__ import annotations

from typing import Dict

from runtime_api_typescript import _strip_block
from sqlonly import strip_sql

JSON = r'''package __PKG__;

import java.math.BigDecimal;
import java.math.BigInteger;
import java.util.ArrayList;
import java.util.Collection;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * JSON senza dipendenze, come lo legge e lo scrive il nucleo delle API: oggetti come LinkedHashMap, array come
 * ArrayList, interi come Long (BigInteger oltre i 64 bit), gli altri numeri come Double. Rifiuta NaN e Infinity.
 */
public final class Json {

    private Json() {
    }

    /** Testo che non è JSON valido. */
    public static final class JsonException extends RuntimeException {
        private static final long serialVersionUID = 1L;

        public JsonException(String message) {
            super(message);
        }
    }

    public static Object parse(String text) {
        Parser p = new Parser(text);
        p.ws();
        Object value = p.value(0);
        p.ws();
        if (p.i != text.length()) throw new JsonException("caratteri dopo il valore JSON");
        return value;
    }

    public static String write(Object value) {
        StringBuilder out = new StringBuilder();
        write(out, value);
        return out.toString();
    }

    private static void write(StringBuilder out, Object v) {
        if (v == null) {
            out.append("null");
        } else if (v instanceof String s) {
            quote(out, s);
        } else if (v instanceof Double d) {
            if (d.isNaN() || d.isInfinite()) throw new JsonException("numero non rappresentabile in JSON");
            out.append(d);
        } else if (v instanceof BigDecimal d) {
            out.append(d.toPlainString());
        } else if (v instanceof Number || v instanceof Boolean) {
            out.append(v);
        } else if (v instanceof Map<?, ?> m) {
            out.append('{');
            boolean first = true;
            for (Map.Entry<?, ?> e : m.entrySet()) {
                if (!first) out.append(',');
                first = false;
                quote(out, String.valueOf(e.getKey()));
                out.append(':');
                write(out, e.getValue());
            }
            out.append('}');
        } else if (v instanceof Collection<?> c) {
            out.append('[');
            boolean first = true;
            for (Object x : c) {
                if (!first) out.append(',');
                first = false;
                write(out, x);
            }
            out.append(']');
        } else {
            quote(out, v.toString());
        }
    }

    private static void quote(StringBuilder out, String s) {
        out.append('"');
        for (int i = 0; i < s.length(); i++) {
            char c = s.charAt(i);
            switch (c) {
                case '"' -> out.append("\\\"");
                case '\\' -> out.append("\\\\");
                case '\n' -> out.append("\\n");
                case '\r' -> out.append("\\r");
                case '\t' -> out.append("\\t");
                default -> {
                    if (c < 0x20) out.append(String.format("\\u%04x", (int) c));
                    else out.append(c);
                }
            }
        }
        out.append('"');
    }

    private static final class Parser {
        private final String s;
        private int i;

        Parser(String s) {
            this.s = s;
        }

        void ws() {
            while (i < s.length() && " \t\r\n".indexOf(s.charAt(i)) >= 0) i++;
        }

        char peek() {
            if (i >= s.length()) throw new JsonException("fine inattesa del testo JSON");
            return s.charAt(i);
        }

        void expect(char c) {
            if (peek() != c) throw new JsonException("atteso '" + c + "' alla posizione " + i);
            i++;
        }

        Object value(int depth) {
            if (depth > 512) throw new JsonException("annidamento eccessivo");
            char c = peek();
            if (c == '{') return object(depth);
            if (c == '[') return array(depth);
            if (c == '"') return string();
            if (s.startsWith("true", i)) return literal(4, Boolean.TRUE);
            if (s.startsWith("false", i)) return literal(5, Boolean.FALSE);
            if (s.startsWith("null", i)) return literal(4, null);
            return number();
        }

        Object literal(int length, Object value) {
            i += length;
            return value;
        }

        Map<String, Object> object(int depth) {
            Map<String, Object> out = new LinkedHashMap<>();
            i++;
            ws();
            if (peek() == '}') {
                i++;
                return out;
            }
            while (true) {
                ws();
                if (peek() != '"') throw new JsonException("attesa una chiave alla posizione " + i);
                String key = string();
                ws();
                expect(':');
                ws();
                out.put(key, value(depth + 1));
                ws();
                if (peek() == '}') {
                    i++;
                    return out;
                }
                expect(',');
            }
        }

        List<Object> array(int depth) {
            List<Object> out = new ArrayList<>();
            i++;
            ws();
            if (peek() == ']') {
                i++;
                return out;
            }
            while (true) {
                ws();
                out.add(value(depth + 1));
                ws();
                if (peek() == ']') {
                    i++;
                    return out;
                }
                expect(',');
            }
        }

        String string() {
            StringBuilder out = new StringBuilder();
            i++;
            while (true) {
                char c = peek();
                i++;
                if (c == '"') return out.toString();
                if (c < 0x20) throw new JsonException("carattere di controllo in una stringa");
                if (c != '\\') {
                    out.append(c);
                    continue;
                }
                char e = peek();
                i++;
                switch (e) {
                    case '"', '\\', '/' -> out.append(e);
                    case 'b' -> out.append('\b');
                    case 'f' -> out.append('\f');
                    case 'n' -> out.append('\n');
                    case 'r' -> out.append('\r');
                    case 't' -> out.append('\t');
                    case 'u' -> {
                        if (i + 4 > s.length()) throw new JsonException("escape unicode incompleto");
                        try {
                            out.append((char) Integer.parseInt(s.substring(i, i + 4), 16));
                        } catch (NumberFormatException ex) {
                            throw new JsonException("escape unicode non valido");
                        }
                        i += 4;
                    }
                    default -> throw new JsonException("escape non valido");
                }
            }
        }

        Object number() {
            int start = i;
            if (peek() == '-') i++;
            if (peek() == '0') {
                i++;
            } else {
                digits();
            }
            boolean integral = true;
            if (i < s.length() && s.charAt(i) == '.') {
                integral = false;
                i++;
                digits();
            }
            if (i < s.length() && (s.charAt(i) == 'e' || s.charAt(i) == 'E')) {
                integral = false;
                i++;
                if (peek() == '+' || peek() == '-') i++;
                digits();
            }
            String text = s.substring(start, i);
            if (integral) {
                BigInteger b = new BigInteger(text);
                return b.bitLength() < 64 ? (Object) b.longValue() : b;
            }
            double d = Double.parseDouble(text);
            if (Double.isInfinite(d)) throw new JsonException("numero fuori intervallo");
            return d;
        }

        void digits() {
            int start = i;
            while (i < s.length() && s.charAt(i) >= '0' && s.charAt(i) <= '9') i++;
            if (i == start) throw new JsonException("cifra attesa alla posizione " + i);
        }
    }
}
'''

SCHEMA = r'''package __PKG__;

import java.math.BigDecimal;
import java.math.BigInteger;
import java.time.DateTimeException;
import java.time.LocalDate;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;
import java.util.Objects;
import java.util.concurrent.ConcurrentHashMap;
import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * Validatore del sottoinsieme di JSON Schema (OpenAPI 3.0) usato dal contratto delle API: stesse regole e stessi
 * testi in tutti i linguaggi. Per ogni campo si riporta la prima regola violata.
 */
public final class JsonSchema {

    private static final Pattern UUID_RE = Pattern.compile("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$");
    private static final Pattern DATE = Pattern.compile("^([0-9]{4})-([0-9]{2})-([0-9]{2})$");
    private static final Pattern DATE_TIME = Pattern.compile(
            "^([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})(\\.[0-9]{1,9})?(Z|[+-]([0-9]{2}):([0-9]{2}))$");
    private static final Pattern INTEGER = Pattern.compile("^-?[0-9]+$");
    private static final Pattern NUMBER = Pattern.compile("^-?[0-9]+(\\.[0-9]+)?([eE][+-]?[0-9]+)?$");
    private static final Map<String, Pattern> PATTERNS = new ConcurrentHashMap<>();

    private JsonSchema() {
    }

    /** Valore di un parametro convertito nel tipo dello schema, oppure la regola violata. */
    public record Coerced(Object value, String error) {
    }

    /** Numero nel testo di una regola: gli interi senza decimali. */
    public static String num(Object x) {
        BigDecimal d = decimal(x).stripTrailingZeros();
        return d.scale() < 0 ? d.setScale(0).toPlainString() : d.toPlainString();
    }

    static BigDecimal decimal(Object x) {
        return new BigDecimal(x.toString());
    }

    private static boolean validDate(Matcher m) {
        try {
            return LocalDate.of(Integer.parseInt(m.group(1)), Integer.parseInt(m.group(2)), Integer.parseInt(m.group(3))).getYear() >= 1;
        } catch (DateTimeException e) {
            return false;
        }
    }

    public static boolean checkFormat(String fmt, String s) {
        if (fmt.equals("uuid")) return UUID_RE.matcher(s).matches();
        if (fmt.equals("date")) {
            Matcher m = DATE.matcher(s);
            return m.matches() && validDate(m);
        }
        Matcher m = DATE_TIME.matcher(s);
        if (!m.matches() || !validDate(m)) return false;
        if (Integer.parseInt(m.group(4)) > 23 || Integer.parseInt(m.group(5)) > 59 || Integer.parseInt(m.group(6)) > 59) return false;
        return m.group(8).equals("Z") || (Integer.parseInt(m.group(9)) <= 23 && Integer.parseInt(m.group(10)) <= 59);
    }

    /** pattern del contratto con la semantica di JavaScript: $ chiude il testo (non accetta un a capo finale). */
    public static Pattern jsPattern(String pattern) {
        return Pattern.compile(pattern.replaceAll("(?<!\\\\)\\$(?=$|\\)|\\|)", "\\\\z"));
    }

    /** Tipo JSON di un valore non nullo (il nullo lo gestisce validate). */
    public static String typeOf(Object v) {
        if (v instanceof Boolean) return "boolean";
        if (v instanceof Long || v instanceof BigInteger) return "integer";
        if (v instanceof Double d) return d == Math.rint(d) ? "integer" : "number";
        if (v instanceof String) return "string";
        if (v instanceof List) return "array";
        return v instanceof Map ? "object" : "unknown";
    }

    private static boolean same(Object a, Object b) {
        if (!typeOf(a).equals(typeOf(b))) return false;
        if (a instanceof Number) return decimal(a).compareTo(decimal(b)) == 0;
        return Objects.equals(a, b);
    }

    /** Aggiunge a errors {percorso: regola} le violazioni di value; un solo errore per percorso. */
    @SuppressWarnings("unchecked")
    public static void validate(Map<String, Object> schema, Object value, String path, Map<String, String> errors) {
        String where = path.isEmpty() ? "body" : path;
        if (errors.containsKey(where)) return;
        if (value == null) {
            if (!Boolean.TRUE.equals(schema.get("nullable")) && schema.containsKey("type")) errors.put(where, "nullo non ammesso");
            return;
        }
        String t = typeOf(value);
        Object want = schema.get("type");
        if (want != null && !(t.equals(want) || (want.equals("number") && t.equals("integer")))) {
            errors.put(where, "tipo atteso: " + want);
            return;
        }
        if (schema.containsKey("enum") && ((List<Object>) schema.get("enum")).stream().noneMatch(e -> same(e, value))) {
            errors.put(where, "valore non ammesso");
            return;
        }
        switch (t) {
            case "string" -> {
                String s = (String) value;
                int n = s.codePointCount(0, s.length());
                if (schema.containsKey("minLength") && n < ((Number) schema.get("minLength")).intValue()) {
                    errors.put(where, "lunghezza minima " + schema.get("minLength"));
                } else if (schema.containsKey("maxLength") && n > ((Number) schema.get("maxLength")).intValue()) {
                    errors.put(where, "lunghezza massima " + schema.get("maxLength"));
                } else if (schema.containsKey("pattern")
                        && !PATTERNS.computeIfAbsent((String) schema.get("pattern"), JsonSchema::jsPattern).matcher(s).find()) {
                    errors.put(where, "formato non valido");
                } else if (schema.containsKey("format") && !checkFormat((String) schema.get("format"), s)) {
                    errors.put(where, "formato " + schema.get("format"));
                }
            }
            case "integer", "number" -> {
                BigDecimal x = decimal(value);
                if (schema.containsKey("minimum") && x.compareTo(decimal(schema.get("minimum"))) < 0) {
                    errors.put(where, "valore minimo " + num(schema.get("minimum")));
                } else if (schema.containsKey("maximum") && x.compareTo(decimal(schema.get("maximum"))) > 0) {
                    errors.put(where, "valore massimo " + num(schema.get("maximum")));
                }
            }
            case "array" -> {
                List<Object> a = (List<Object>) value;
                if (schema.containsKey("minItems") && a.size() < ((Number) schema.get("minItems")).intValue()) {
                    errors.put(where, "almeno " + schema.get("minItems") + " elementi");
                } else if (schema.containsKey("maxItems") && a.size() > ((Number) schema.get("maxItems")).intValue()) {
                    errors.put(where, "al massimo " + schema.get("maxItems") + " elementi");
                } else if (schema.containsKey("items")) {
                    for (int i = 0; i < a.size(); i++) validate((Map<String, Object>) schema.get("items"), a.get(i), path + "[" + i + "]", errors);
                }
            }
            case "object" -> {
                Map<String, Object> o = (Map<String, Object>) value;
                Map<String, Object> props = (Map<String, Object>) schema.getOrDefault("properties", Map.of());
                String prefix = path.isEmpty() ? "" : path + ".";
                for (Object name : (List<Object>) schema.getOrDefault("required", List.of())) {
                    if (!o.containsKey((String) name)) errors.putIfAbsent(prefix + name, "obbligatorio");
                }
                for (Map.Entry<String, Object> p : props.entrySet()) {
                    if (o.containsKey(p.getKey())) validate((Map<String, Object>) p.getValue(), o.get(p.getKey()), prefix + p.getKey(), errors);
                }
                Object extra = schema.getOrDefault("additionalProperties", Boolean.TRUE);
                for (String name : o.keySet()) {
                    if (props.containsKey(name)) continue;
                    if (Boolean.FALSE.equals(extra)) {
                        errors.putIfAbsent(prefix + name, "non ammesso");
                    } else if (extra instanceof Map) {
                        validate((Map<String, Object>) extra, o.get(name), prefix + name, errors);
                    }
                }
            }
            default -> {
                // boolean: nessuna regola oltre al tipo
            }
        }
    }

    /** Valore di un parametro di path o query (testo) nel tipo dello schema. */
    @SuppressWarnings("unchecked")
    public static Coerced coerce(Map<String, Object> schema, List<String> raw) {
        Object type = schema.get("type");
        if ("array".equals(type)) {
            Map<String, Object> items = (Map<String, Object>) schema.getOrDefault("items", Map.of());
            List<Object> out = new ArrayList<>();
            for (String r : raw) {
                Coerced c = coerce(items, List.of(r));
                if (c.error() != null) return new Coerced(null, c.error());
                out.add(c.value());
            }
            return new Coerced(out, null);
        }
        if (raw.size() != 1) return new Coerced(null, "un solo valore");
        String r = raw.get(0);
        if ("integer".equals(type)) {
            if (!INTEGER.matcher(r).matches()) return new Coerced(null, "tipo atteso: integer");
            BigInteger b = new BigInteger(r);
            return new Coerced(b.bitLength() < 64 ? (Object) b.longValue() : b, null);
        }
        if ("number".equals(type)) {
            double x = NUMBER.matcher(r).matches() ? Double.parseDouble(r) : Double.POSITIVE_INFINITY;
            return Double.isFinite(x) ? new Coerced(x, null) : new Coerced(null, "tipo atteso: number");
        }
        if ("boolean".equals(type)) {
            return r.equals("true") || r.equals("false") ? new Coerced(r.equals("true"), null) : new Coerced(null, "tipo atteso: boolean");
        }
        return new Coerced(r, null);
    }
}
'''

REQUEST = r'''package __PKG__;

import java.net.URLDecoder;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * Richiesta HTTP indipendente dal runtime (Lambda, server del JDK, Spring): nomi degli header in minuscolo, corpo
 * grezzo (null se assente), identità dai claim già verificati dal gateway (null se assente).
 */
public record ApiRequest(String method, String path, Map<String, List<String>> query, Map<String, String> headers, byte[] body,
                         Identity identity) {

    /** Query string grezza (a=1&b=x%20y) -> {nome: valori}. */
    public static Map<String, List<String>> parseQuery(String raw) {
        Map<String, List<String>> out = new LinkedHashMap<>();
        if (raw == null) return out;
        for (String part : raw.split("&")) {
            if (part.isEmpty()) continue;
            int eq = part.indexOf('=');
            String name = eq < 0 ? part : part.substring(0, eq);
            String value = eq < 0 ? "" : part.substring(eq + 1);
            out.computeIfAbsent(decode(name, true), k -> new ArrayList<>()).add(decode(value, true));
        }
        return out;
    }

    /** Percent-decoding UTF-8; form: '+' vale spazio (query), altrimenti resta '+' (percorso). Se malformato resta com'è. */
    public static String decode(String s, boolean form) {
        try {
            return URLDecoder.decode(form ? s : s.replace("+", "%2B"), StandardCharsets.UTF_8);
        } catch (IllegalArgumentException e) {
            return s;
        }
    }
}
'''

RESPONSE = r'''package __PKG__;

import java.util.LinkedHashMap;
import java.util.Map;

/** Risposta HTTP: stato, corpo JSON (hasBody false per 204 e simili) e header. */
public record ApiResponse(int status, Object body, Map<String, String> headers, boolean hasBody) {

    /** Risposta senza corpo costruita dal service. */
    public static ApiResponse reply(int status) {
        return new ApiResponse(status, null, new LinkedHashMap<>(), false);
    }

    /** Risposta JSON costruita dal service (stato proprio). */
    public static ApiResponse reply(int status, Object body) {
        Map<String, String> headers = new LinkedHashMap<>();
        headers.put("content-type", "application/json");
        return new ApiResponse(status, body, headers, true);
    }

    /** Risposta JSON con header propri (es. location). */
    public static ApiResponse reply(int status, Object body, Map<String, String> headers) {
        return new ApiResponse(status, body, new LinkedHashMap<>(headers), true);
    }

    /** Corpo come testo JSON ("" senza corpo). */
    public String text() {
        return hasBody ? Json.write(body) : "";
    }
}
'''

ERROR = r'''package __PKG__;

import java.util.LinkedHashMap;
import java.util.Map;

/** Errore applicativo con esito HTTP: kind è una chiave di Errors.STATUS, fields {campo: regola}. */
public final class ApiError extends RuntimeException {
    private static final long serialVersionUID = 1L;

    private final String kind;
    private final String code;
    private final transient Map<String, String> fields;

    public ApiError(String kind, String code) {
        this(kind, code, Map.of());
    }

    public ApiError(String kind, String code, Map<String, String> fields) {
        super(code);
        this.kind = kind;
        this.code = code;
        this.fields = new LinkedHashMap<>(fields);
    }

    public String kind() {
        return kind;
    }

    public String code() {
        return code;
    }

    public Map<String, String> fields() {
        return fields;
    }
}
'''

ERRORS = r'''package __PKG__;

import java.util.LinkedHashMap;
import java.util.Map;

/** Errore -> stato HTTP; il messaggio pubblico non contiene dettagli (che restano nei log, con il correlationId). */
public final class Errors {

    public static final Map<String, Integer> STATUS = Map.ofEntries(
            Map.entry("VALIDATION", 400), Map.entry("AUTH", 401), Map.entry("FORBIDDEN", 403), Map.entry("NOT_FOUND", 404),
            Map.entry("METHOD_NOT_ALLOWED", 405), Map.entry("CONFLICT", 409), Map.entry("UNSUPPORTED_MEDIA_TYPE", 415),
            Map.entry("UNPROCESSABLE", 422), Map.entry("INTERNAL", 500), Map.entry("TRANSIENT", 503));

    public static final Map<String, String> MESSAGE = Map.ofEntries(
            Map.entry("VALIDATION", "Richiesta non valida"), Map.entry("AUTH", "Autenticazione richiesta"),
            Map.entry("FORBIDDEN", "Operazione non consentita"), Map.entry("NOT_FOUND", "Risorsa non trovata"),
            Map.entry("METHOD_NOT_ALLOWED", "Metodo non ammesso"), Map.entry("CONFLICT", "Conflitto con lo stato attuale"),
            Map.entry("UNSUPPORTED_MEDIA_TYPE", "Serve un corpo application/json"),
            Map.entry("UNPROCESSABLE", "Dati non accettati dal modello"), Map.entry("INTERNAL", "Errore interno"),
            Map.entry("TRANSIENT", "Servizio temporaneamente non disponibile"));

    private Errors() {
    }

    /** {"error": {"code", "message", "correlationId", "fields"?}} */
    public static Map<String, Object> errorBody(String kind, String code, String cid, Map<String, String> fields) {
        Map<String, Object> error = new LinkedHashMap<>();
        error.put("code", code);
        error.put("message", MESSAGE.get(kind));
        error.put("correlationId", cid);
        if (fields != null && !fields.isEmpty()) error.put("fields", fields);
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("error", error);
        return out;
    }
}
'''

TYPES = r'''package __PKG__;

import java.util.Map;
import java.util.Set;

/** Chi chiama: claim già verificati dal gateway (mai il token grezzo). */
public record Identity(String subject, String tenant, Set<String> scopes, Map<String, Object> claims) {

    public static Identity anonymous() {
        return new Identity(null, null, Set.of(), Map.of());
    }
}
'''

CALL = r'''package __PKG__;

import java.util.Map;

/** Input già validato di un'operazione, passato al controller generato o al metodo del service. */
public record Call(String operation, Map<String, Object> path, Map<String, Object> query, Object body, Identity identity,
                   String correlationId, String tenant, String basePath) {
}
'''

HANDLER = r'''package __PKG__;

/** Esegue un'operazione: restituisce il corpo JSON della risposta (stato del contratto) o un ApiResponse. */
@FunctionalInterface
public interface Handler {
    Object handle(Call call);
}
'''

CONTROLLER = r'''package __PKG__;

/** Controller generato di un'operazione CRUD, di query o di relazione. */
@FunctionalInterface
public interface Controller {
    Object handle(ApiData data, Call call);
}
'''

IDENTITY = r'''package __PKG__;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Identità dai claim già verificati dal gateway: requestContext.authorizer (Lambda) o header impostati dal gateway.
 * Il servizio non verifica il token: deve essere raggiungibile solo dal gateway (rete privata, VPC link), che
 * sovrascrive gli header di identità a ogni richiesta.
 */
public final class IdentityReader {

    public static final String CLAIM_SUBJECT = __CLAIM_SUBJECT__;
    public static final String CLAIM_TENANT = __CLAIM_TENANT__;
    public static final List<String> CLAIM_SCOPES = List.of(__CLAIM_SCOPES__);
    public static final String HEADER_SUBJECT = __HEADER_SUBJECT__;
    public static final String HEADER_TENANT = __HEADER_TENANT__;
    public static final String HEADER_SCOPES = __HEADER_SCOPES__;

    private IdentityReader() {
    }

    /** Scope da un claim: lista, "a b", "a,b" o "[a b]" (forma degli array nei claim di API Gateway HTTP API). */
    public static List<String> scopesOf(Object value) {
        List<String> out = new ArrayList<>();
        if (value == null) return out;
        if (value instanceof List<?> list) {
            for (Object x : list) out.add(String.valueOf(x));
            return out;
        }
        String text = value.toString().trim();
        if (text.startsWith("[") && text.endsWith("]")) text = text.substring(1, text.length() - 1);
        for (String s : text.replace(',', ' ').split("\\s+")) {
            if (!s.isEmpty()) out.add(s);
        }
        return out;
    }

    private static String opt(Object v) {
        return v == null || "".equals(v) ? null : v.toString();
    }

    public static Identity fromClaims(Map<String, Object> claims) {
        Set<String> scopes = new LinkedHashSet<>();
        for (String name : CLAIM_SCOPES) scopes.addAll(scopesOf(claims.get(name)));
        return new Identity(opt(claims.get(CLAIM_SUBJECT)), opt(claims.get(CLAIM_TENANT)), scopes, new LinkedHashMap<>(claims));
    }

    /** API Gateway: HTTP API (authorizer.jwt.claims o authorizer.lambda) o REST API (authorizer.claims o contesto). */
    @SuppressWarnings("unchecked")
    public static Identity fromLambda(Map<String, Object> event) {
        Object context = event.get("requestContext");
        Object auth = context instanceof Map<?, ?> c ? c.get("authorizer") : null;
        if (!(auth instanceof Map<?, ?> a)) return null;
        Object jwt = a.get("jwt");
        Object claims = jwt instanceof Map<?, ?> j ? j.get("claims") : null;
        if (claims == null) claims = a.get("lambda");
        if (claims == null) claims = a.get("claims");
        if (claims == null) claims = a;
        if (claims instanceof String s) claims = Json.parse(s); // authorizer Lambda di REST API: claim come JSON
        return fromClaims((Map<String, Object>) claims);
    }

    /** Kubernetes dietro il gateway: claim copiati negli header dal parameter mapping del gateway. */
    public static Identity fromHeaders(Map<String, String> headers) {
        if (!headers.containsKey(HEADER_SUBJECT)) return null;
        Map<String, Object> claims = new LinkedHashMap<>();
        claims.put(CLAIM_SUBJECT, headers.get(HEADER_SUBJECT));
        if (headers.containsKey(HEADER_TENANT)) claims.put(CLAIM_TENANT, headers.get(HEADER_TENANT));
        if (headers.containsKey(HEADER_SCOPES)) claims.put(CLAIM_SCOPES.get(0), headers.get(HEADER_SCOPES));
        return fromClaims(claims);
    }
}
'''

SPEC = r'''package __PKG__;

import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/** Operazione del contratto: percorso, metodo, contesto, scope, schemi di parametri e corpo. */
public record Spec(String id, String method, String path, String context, String kind, String table, String arg, int status,
                   boolean secured, List<String> scopes, List<Param> params, Map<String, Object> body, boolean bodyRequired) {

    /** Parametro di path o query. */
    public record Param(String name, String in, boolean required, Map<String, Object> schema) {
    }

    /** Spec dalla sua forma JSON (incorporata nel codice generato). */
    @SuppressWarnings("unchecked")
    public static Spec of(String json) {
        Map<String, Object> m = (Map<String, Object>) Json.parse(json);
        List<Param> params = new ArrayList<>();
        for (Object o : (List<Object>) m.get("params")) {
            Map<String, Object> p = (Map<String, Object>) o;
            params.add(new Param((String) p.get("name"), (String) p.get("in"), (Boolean) p.get("required"), (Map<String, Object>) p.get("schema")));
        }
        List<String> scopes = new ArrayList<>();
        for (Object s : (List<Object>) m.get("scopes")) scopes.add((String) s);
        return new Spec((String) m.get("id"), (String) m.get("method"), (String) m.get("path"), (String) m.get("context"),
                (String) m.get("kind"), (String) m.get("table"), (String) m.get("arg"), ((Number) m.get("status")).intValue(),
                (Boolean) m.get("secured"), List.copyOf(scopes), List.copyOf(params), (Map<String, Object>) m.get("body"),
                (Boolean) m.get("bodyRequired"));
    }
}
'''

ROUTE = r'''package __PKG__;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/** Un'operazione con il suo handler e i segmenti del percorso. */
public final class Route {

    private final Spec spec;
    private final Handler handler;
    private final List<String> segments = new ArrayList<>();

    public Route(Spec spec, Handler handler) {
        this.spec = spec;
        this.handler = handler;
        for (String s : spec.path().split("/")) {
            if (!s.isEmpty()) segments.add(s);
        }
    }

    public Spec spec() {
        return spec;
    }

    public Handler handler() {
        return handler;
    }

    /** Parametri di percorso se parts corrisponde, altrimenti null. */
    public Map<String, String> match(List<String> parts) {
        if (parts.size() != segments.size()) return null;
        Map<String, String> out = new LinkedHashMap<>();
        for (int i = 0; i < parts.size(); i++) {
            String seg = segments.get(i);
            if (seg.startsWith("{")) out.put(seg.substring(1, seg.length() - 1), parts.get(i));
            else if (!seg.equals(parts.get(i))) return null;
        }
        return out;
    }

    /** I segmenti fissi vincono sui parametri, da sinistra a destra. */
    public String rank() {
        StringBuilder out = new StringBuilder();
        for (String s : segments) out.append(s.startsWith("{") ? '1' : '0');
        return out.toString();
    }
}
'''

ROUTER = r'''package __PKG__;

// Router e middleware delle API: correlationId, percorso e metodo, identità e scope, validazione, errori.
// Ordine per ogni richiesta (uguale in tutti i linguaggi):
//   1. correlationId dall'header x-correlation-id (se valido) o nuovo;
//   2. operazione dal percorso (i segmenti fissi vincono sui parametri) e dal metodo: 404 o 405;
//   3. identità obbligatoria per le operazioni protette (401) e scope richiesti (403);
//   4. parametri di path e query: tipi, regole, parametri sconosciuti (400);
//   5. corpo: application/json (415), JSON valido e conforme allo schema (400);
//   6. controller o metodo del service; errori del modello e del database -> 404, 409, 422, 503; il resto -> 500.

import __MGEN__.ModelValidationException;
import __MGEN__.Tenancy;
// kybes:sql-begin
import __MGEN__.UnitOfWork;
import jakarta.persistence.EntityNotFoundException;
import java.sql.SQLException;
// kybes:sql-end
// kybes:mongo-begin
import com.mongodb.MongoException;
// kybes:mongo-end
import java.nio.ByteBuffer;
import java.nio.charset.CharacterCodingException;
import java.nio.charset.CodingErrorAction;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.HashSet;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import java.util.TreeSet;
import java.util.UUID;
import java.util.regex.Pattern;

/** Le operazioni del contratto con i loro handler: handle(ApiRequest) -> ApiResponse. */
public final class Api {

    private static final Pattern CID = Pattern.compile("^[A-Za-z0-9._-]{1,128}$");
    private static final Set<String> PAGING_FIELDS = Set.of("limit", "sort", "cursor");
    private static final Set<String> SHOWN = Set.of("VALIDATION", "CONFLICT", "UNPROCESSABLE");
    private static final System.Logger LOG = System.getLogger("kybes.api");

    private final List<Route> routes;
    private final String basePath;

    public Api(List<Spec> specs, Map<String, Handler> handlers, String basePath) {
        List<Route> out = new ArrayList<>();
        for (Spec s : specs) out.add(new Route(s, handlers.get(s.id())));
        out.sort(Comparator.comparing(Route::rank));
        this.routes = List.copyOf(out);
        this.basePath = basePath.replaceAll("/+$", "");
    }

    public List<Route> routes() {
        return routes;
    }

    public String basePath() {
        return basePath;
    }

    /** Errore del modello, del database o inatteso -> errore dell'API. */
    public static ApiError mapError(Throwable err) {
        if (err instanceof ApiError e) return e;
        if (err instanceof ModelValidationException e) {
            Map<String, String> fields = new LinkedHashMap<>(e.getFields());
            if (!fields.isEmpty() && PAGING_FIELDS.containsAll(fields.keySet())) return new ApiError("VALIDATION", "INVALID_PAGE", fields);
            if (!fields.isEmpty() && fields.values().stream().allMatch("record collegati"::equals)) {
                return new ApiError("CONFLICT", "RELATED_RECORDS", fields);
            }
            return new ApiError("UNPROCESSABLE", "MODEL_RULE", fields);
        }
        if (err instanceof Tenancy.TenantException) return new ApiError("FORBIDDEN", "TENANT_REQUIRED");
        // kybes:mongo-begin
        for (Throwable e = err; e != null; e = e.getCause()) {
            if (e instanceof MongoException m && m.getCode() == 11000) return new ApiError("CONFLICT", "DUPLICATE");
        }
        // kybes:mongo-end
        // kybes:sql-begin
        if (err instanceof EntityNotFoundException) return new ApiError("NOT_FOUND", "RECORD_NOT_FOUND");
        for (Throwable e = err; e != null; e = e.getCause()) {
            if (e instanceof SQLException s && s.getSQLState() != null && s.getSQLState().startsWith("23")) {
                return new ApiError("CONFLICT", "CONSTRAINT");
            }
        }
        if (UnitOfWork.isRetryable(err)) return new ApiError("TRANSIENT", "RETRY_LATER");
        // kybes:sql-end
        return new ApiError("INTERNAL", "UNEXPECTED");
    }

    public ApiResponse handle(ApiRequest req) {
        String given = req.headers().getOrDefault("x-correlation-id", "");
        String cid = CID.matcher(given).matches() ? given : UUID.randomUUID().toString();
        ApiResponse resp;
        try {
            resp = dispatch(req, cid);
        } catch (RuntimeException exc) {
            ApiError err = mapError(exc);
            if (err.kind().equals("INTERNAL")) {
                LOG.log(System.Logger.Level.ERROR, "{\"level\":\"error\",\"msg\":\"api: errore inatteso\",\"correlationId\":\"" + cid + "\"}", exc);
            }
            Map<String, String> headers = new LinkedHashMap<>();
            headers.put("content-type", "application/json");
            Map<String, String> fields = new LinkedHashMap<>(err.fields());
            if (err.kind().equals("METHOD_NOT_ALLOWED")) headers.put("allow", fields.remove("allow"));
            resp = new ApiResponse(Errors.STATUS.get(err.kind()), Errors.errorBody(err.kind(), err.code(), cid,
                    SHOWN.contains(err.kind()) ? fields : null), headers, true);
        }
        resp.headers().put("x-correlation-id", cid);
        return resp;
    }

    private Map.Entry<Route, Map<String, String>> find(ApiRequest req) {
        String path = req.path();
        if (!basePath.isEmpty() && (path.equals(basePath) || path.startsWith(basePath + "/"))) path = path.substring(basePath.length());
        List<String> parts = new ArrayList<>();
        for (String p : path.split("/")) {
            if (!p.isEmpty()) parts.add(ApiRequest.decode(p, false));
        }
        Set<String> allowed = new TreeSet<>();
        String method = req.method().toUpperCase(Locale.ROOT);
        for (Route r : routes) {
            Map<String, String> params = r.match(parts);
            if (params == null) continue;
            if (r.spec().method().equals(method)) return Map.entry(r, params);
            allowed.add(r.spec().method());
        }
        if (!allowed.isEmpty()) throw new ApiError("METHOD_NOT_ALLOWED", "METHOD_NOT_ALLOWED", Map.of("allow", String.join(", ", allowed)));
        throw new ApiError("NOT_FOUND", "ROUTE_NOT_FOUND");
    }

    private ApiResponse dispatch(ApiRequest req, String cid) {
        Map.Entry<Route, Map<String, String>> found = find(req);
        Route route = found.getKey();
        Spec spec = route.spec();
        Identity identity = req.identity() != null ? req.identity() : Identity.anonymous();
        if (spec.secured() && identity.subject() == null) throw new ApiError("AUTH", "IDENTITY_REQUIRED");
        if (!identity.scopes().containsAll(spec.scopes())) throw new ApiError("FORBIDDEN", "SCOPE_REQUIRED");
        Map<String, String> errors = new LinkedHashMap<>();
        Map<String, Object> pathValues = new LinkedHashMap<>();
        Map<String, Object> queryValues = new LinkedHashMap<>();
        Set<String> known = new HashSet<>();
        for (Spec.Param p : spec.params()) {
            if (p.in().equals("query")) known.add(p.name());
        }
        for (String name : req.query().keySet()) {
            if (!known.contains(name)) errors.put(name, "parametro sconosciuto");
        }
        for (Spec.Param p : spec.params()) {
            boolean inPath = p.in().equals("path");
            List<String> raw = inPath ? List.of(found.getValue().get(p.name())) : req.query().get(p.name());
            if (raw == null) {
                if (p.required()) errors.putIfAbsent(p.name(), "obbligatorio");
                continue;
            }
            JsonSchema.Coerced c = JsonSchema.coerce(p.schema(), raw);
            if (c.error() != null) {
                errors.putIfAbsent(p.name(), c.error());
                continue;
            }
            JsonSchema.validate(p.schema(), c.value(), p.name(), errors);
            (inPath ? pathValues : queryValues).put(p.name(), c.value());
        }
        Object body = null;
        boolean hasBody = req.body() != null && req.body().length > 0;
        if (spec.body() == null) {
            if (hasBody) errors.putIfAbsent("body", "corpo non ammesso");
        } else if (hasBody) {
            String ctype = req.headers().getOrDefault("content-type", "").split(";")[0].trim().toLowerCase(Locale.ROOT);
            if (!ctype.equals("application/json")) throw new ApiError("UNSUPPORTED_MEDIA_TYPE", "JSON_REQUIRED");
            try {
                body = Json.parse(StandardCharsets.UTF_8.newDecoder().onMalformedInput(CodingErrorAction.REPORT)
                        .onUnmappableCharacter(CodingErrorAction.REPORT).decode(ByteBuffer.wrap(req.body())).toString());
            } catch (CharacterCodingException | Json.JsonException e) {
                errors.putIfAbsent("body", "JSON non valido");
            }
            if (!errors.containsKey("body")) JsonSchema.validate(spec.body(), body, "", errors);
        } else if (spec.bodyRequired()) {
            errors.putIfAbsent("body", "obbligatorio");
        }
        if (!errors.isEmpty()) throw new ApiError("VALIDATION", "INVALID_REQUEST", errors);
        Object result = route.handler().handle(new Call(spec.id(), pathValues, queryValues, body, identity, cid, identity.tenant(), basePath));
        if (result instanceof ApiResponse r) {
            Map<String, String> headers = new LinkedHashMap<>(r.headers());
            if (r.hasBody()) headers.putIfAbsent("content-type", "application/json");
            return new ApiResponse(r.status(), r.body(), headers, r.hasBody());
        }
        if (spec.status() == 204) return ApiResponse.reply(204);
        return ApiResponse.reply(spec.status(), result);
    }
}
'''

DATA = r'''package __PKG__;

// kybes:sql-begin
import __MGEN__.Tenancy;
import __MGEN__.UnitOfWork;
import jakarta.persistence.EntityManager;
import jakarta.persistence.EntityManagerFactory;
import java.util.Collection;
// kybes:sql-end
// kybes:mongo-begin
import __MGEN__.MongoSession;
import com.mongodb.client.MongoClient;
// kybes:mongo-end
import java.util.function.Function;

/**
 * Accesso ai dati per i controller generati: letture con il tenant legato, scritture in una Unit of Work (tabelle SQL)
 * o in una transazione MongoDB (collection).
 */
public final class ApiData {

    // kybes:sql-begin
    private EntityManagerFactory emf;
    private Function<String, EntityManagerFactory> sqlFor;
    // kybes:sql-end
    // kybes:mongo-begin
    private MongoClient mongoClient;
    private String mongoDatabase;
    private Function<String, String> mongoDatabaseFor;
    // kybes:mongo-end

    // kybes:sql-begin
    /** EntityManagerFactory delle tabelle SQL. */
    public ApiData emf(EntityManagerFactory value) {
        this.emf = value;
        return this;
    }

    /** EntityManagerFactory per tenant, per le tabelle con tenancy schema o database. */
    public ApiData sqlFor(Function<String, EntityManagerFactory> value) {
        this.sqlFor = value;
        return this;
    }

    private EntityManagerFactory sql(String tenant) {
        EntityManagerFactory f = sqlFor != null ? sqlFor.apply(tenant) : emf;
        if (f == null) throw new IllegalStateException("ApiData: serve emf (o sqlFor) per le tabelle SQL");
        return f;
    }

    public <T> T read(String tenant, Function<EntityManager, T> work) {
        EntityManager em = sql(tenant).createEntityManager();
        try {
            if (tenant != null) Tenancy.bind(em, tenant);
            return work.apply(em);
        } finally {
            em.close();
        }
    }

    public <T> T write(Collection<String> tables, String tenant, Function<EntityManager, T> work) {
        return UnitOfWork.run(sql(tenant), work, tables, null, 3, 50, tenant);
    }
    // kybes:sql-end

    // kybes:mongo-begin
    /** Client MongoDB e database delle collection. */
    public ApiData mongo(MongoClient client, String database) {
        this.mongoClient = client;
        this.mongoDatabase = database;
        return this;
    }

    /** Database per tenant, per le collection con tenancy database. */
    public ApiData mongoDatabaseFor(Function<String, String> value) {
        this.mongoDatabaseFor = value;
        return this;
    }

    private String database(String tenant) {
        if (mongoClient == null) throw new IllegalStateException("ApiData: serve mongo(client, database) per le collection MongoDB");
        return mongoDatabaseFor != null ? mongoDatabaseFor.apply(tenant) : mongoDatabase;
    }

    public <T> T mongoRead(String tenant, Function<MongoSession, T> work) {
        String db = database(tenant);
        return work.apply(MongoSession.open(mongoClient, db, tenant));
    }

    public <T> T mongoWrite(String tenant, Function<MongoSession, T> work) {
        String db = database(tenant);
        return MongoSession.transaction(mongoClient, db, work, tenant);
    }
    // kybes:mongo-end
}
'''

CONVERT = r'''package __PKG__;

import __MGEN__.Paging;
import java.math.BigDecimal;
import java.math.RoundingMode;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.time.ZoneOffset;
import java.time.format.DateTimeFormatter;
import java.time.temporal.ChronoUnit;
import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import java.util.function.Function;

/**
 * Conversioni tra il JSON delle API e i valori del modello (uguali in tutti i linguaggi): uuid, bigint e decimal come
 * stringhe; date "AAAA-MM-GG"; datetime ISO 8601 in UTC al millisecondo ("...Z"); json come testo nel modello.
 */
public final class Convert {

    private static final DateTimeFormatter DT = DateTimeFormatter.ofPattern("uuuu-MM-dd'T'HH:mm:ss.SSS'Z'");

    private Convert() {
    }

    public static UUID toUuid(Object v) {
        return v == null ? null : UUID.fromString(v.toString());
    }

    public static Integer toInt(Object v) {
        return v == null ? null : ((Number) v).intValue();
    }

    public static Long toBigint(Object v) {
        return v == null ? null : Long.valueOf(v.toString());
    }

    public static BigDecimal toDecimal(Object v) {
        return v == null ? null : new BigDecimal(v.toString());
    }

    public static LocalDate toDate(Object v) {
        return v == null ? null : LocalDate.parse(v.toString());
    }

    public static OffsetDateTime toDatetime(Object v) {
        return v == null ? null : OffsetDateTime.parse(v.toString()).truncatedTo(ChronoUnit.MILLIS);
    }

    public static String toJsonText(Object v) {
        return v == null ? null : Json.write(v);
    }

    /** Ogni elemento di una lista (parametro di query con op in) convertito con f. */
    public static <T> List<T> each(Object v, Function<Object, T> f) {
        List<T> out = new ArrayList<>();
        for (Object x : (List<?>) v) out.add(f.apply(x));
        return out;
    }

    public static String uuidText(UUID v) {
        return v == null ? null : v.toString();
    }

    public static String text(Object v) {
        return v == null ? null : v.toString();
    }

    public static String decimalText(BigDecimal v, int scale) {
        return v == null ? null : v.setScale(scale, RoundingMode.DOWN).toPlainString();
    }

    public static String dateText(LocalDate v) {
        return v == null ? null : v.toString();
    }

    public static String datetimeText(OffsetDateTime v) {
        return v == null ? null : DT.format(v.withOffsetSameInstant(ZoneOffset.UTC));
    }

    public static Object jsonValue(String v) {
        return v == null ? null : Json.parse(v);
    }

    /** Pagina del modello nel formato del contratto. */
    public static <T> Map<String, Object> page(Paging.Page<T> p, Function<T, Map<String, Object>> conv) {
        List<Object> items = new ArrayList<>();
        for (T x : p.items()) items.add(conv.apply(x));
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("items", items);
        out.put("nextCursor", p.nextCursor());
        out.put("limit", p.limit());
        return out;
    }

    /** limit, cursor e sort della query come richiesta di pagina. */
    public static Paging.PageRequest request(Map<String, Object> q) {
        return new Paging.PageRequest(toInt(q.get("limit")), (String) q.get("cursor"), (String) q.get("sort"));
    }
}
'''

LAMBDA = r'''package __PKG__;

import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.Base64;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * Adattatore AWS Lambda (API Gateway HTTP API v2 e REST API v1): evento -> ApiRequest -> risposta proxy.
 * Handler POJO della function: public Map&lt;String, Object&gt; handleRequest(Map&lt;String, Object&gt; event) {
 * return LambdaAdapter.handle(API, event); }
 */
public final class LambdaAdapter {

    private LambdaAdapter() {
    }

    @SuppressWarnings("unchecked")
    public static ApiRequest toRequest(Map<String, Object> event) {
        Map<String, String> headers = new LinkedHashMap<>();
        if (event.get("headers") instanceof Map<?, ?> h) {
            for (Map.Entry<?, ?> e : h.entrySet()) headers.put(e.getKey().toString().toLowerCase(Locale.ROOT), String.valueOf(e.getValue()));
        }
        byte[] body = null;
        Object raw = event.get("body");
        if (raw != null) {
            body = Boolean.TRUE.equals(event.get("isBase64Encoded")) ? Base64.getDecoder().decode(raw.toString())
                    : raw.toString().getBytes(StandardCharsets.UTF_8);
        }
        Map<String, List<String>> query;
        String method;
        String path;
        if ("2.0".equals(event.get("version"))) {
            Map<String, Object> http = (Map<String, Object>) ((Map<String, Object>) event.get("requestContext")).get("http");
            method = String.valueOf(http.get("method"));
            path = orRoot(event.get("rawPath"));
            query = ApiRequest.parseQuery((String) event.get("rawQueryString"));
        } else {
            method = String.valueOf(event.get("httpMethod"));
            path = orRoot(event.get("path"));
            query = new LinkedHashMap<>();
            if (event.get("multiValueQueryStringParameters") instanceof Map<?, ?> multi) {
                for (Map.Entry<?, ?> e : multi.entrySet()) {
                    List<String> values = new ArrayList<>();
                    for (Object x : (List<?>) e.getValue()) values.add(String.valueOf(x));
                    query.put(e.getKey().toString(), values);
                }
            } else if (event.get("queryStringParameters") instanceof Map<?, ?> single) {
                for (Map.Entry<?, ?> e : single.entrySet()) query.put(e.getKey().toString(), List.of(String.valueOf(e.getValue())));
            }
        }
        return new ApiRequest(method, path, query, headers, body, IdentityReader.fromLambda(event));
    }

    private static String orRoot(Object p) {
        return p == null || p.toString().isEmpty() ? "/" : p.toString();
    }

    public static Map<String, Object> toProxy(ApiResponse resp) {
        Map<String, Object> out = new LinkedHashMap<>();
        out.put("statusCode", resp.status());
        out.put("headers", new LinkedHashMap<>(resp.headers()));
        out.put("isBase64Encoded", false);
        out.put("body", resp.text());
        return out;
    }

    public static Map<String, Object> handle(Api api, Map<String, Object> event) {
        return toProxy(api.handle(toRequest(event)));
    }
}
'''

JDK_HTTP = r'''package __PKG__;

import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpHandler;
import java.io.IOException;
import java.io.OutputStream;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;

/**
 * Adattatore per il server HTTP del JDK (com.sun.net.httpserver), senza framework, per i microservizi su Kubernetes
 * dietro il gateway: server.createContext("/", HttpServerAdapter.handler(api)).
 */
public final class HttpServerAdapter {

    private HttpServerAdapter() {
    }

    public static ApiRequest readRequest(HttpExchange exchange) throws IOException {
        byte[] body = exchange.getRequestBody().readAllBytes();
        Map<String, String> headers = new LinkedHashMap<>();
        for (Map.Entry<String, List<String>> e : exchange.getRequestHeaders().entrySet()) {
            headers.put(e.getKey().toLowerCase(Locale.ROOT), String.join(", ", e.getValue()));
        }
        URI uri = exchange.getRequestURI();
        return new ApiRequest(exchange.getRequestMethod(), uri.getRawPath(), ApiRequest.parseQuery(uri.getRawQuery()), headers,
                body.length > 0 ? body : null, IdentityReader.fromHeaders(headers));
    }

    public static void writeResponse(HttpExchange exchange, ApiResponse resp) throws IOException {
        byte[] out = resp.text().getBytes(StandardCharsets.UTF_8);
        for (Map.Entry<String, String> h : resp.headers().entrySet()) exchange.getResponseHeaders().set(h.getKey(), h.getValue());
        exchange.sendResponseHeaders(resp.status(), out.length == 0 ? -1 : out.length);
        try (OutputStream os = exchange.getResponseBody()) {
            os.write(out);
        }
    }

    public static HttpHandler handler(Api api) {
        return exchange -> {
            try {
                writeResponse(exchange, api.handle(readRequest(exchange)));
            } finally {
                exchange.close();
            }
        };
    }
}
'''

SPRING = r'''package __PKG__;

import jakarta.servlet.http.HttpServletRequest;
import java.io.IOException;
import java.net.URI;
import java.nio.charset.StandardCharsets;
import java.util.Collections;
import java.util.LinkedHashMap;
import java.util.LinkedHashSet;
import java.util.Locale;
import java.util.Map;
import java.util.Set;
import org.springframework.web.servlet.function.HandlerFunction;
import org.springframework.web.servlet.function.RequestPredicates;
import org.springframework.web.servlet.function.RouterFunction;
import org.springframework.web.servlet.function.RouterFunctions;
import org.springframework.web.servlet.function.ServerRequest;
import org.springframework.web.servlet.function.ServerResponse;

/**
 * Adattatore Spring Boot (Web MVC funzionale): ogni percorso del contratto diventa una route; validazione, errori e
 * identità restano del nucleo. @Bean RouterFunction&lt;ServerResponse&gt; api() { return SpringAdapter.routes(api); }
 * Dipendenza opzionale: spring-webmvc serve solo a chi usa questo adattatore.
 */
public final class SpringAdapter {

    private SpringAdapter() {
    }

    public static ApiRequest toRequest(ServerRequest request) throws IOException {
        HttpServletRequest http = request.servletRequest();
        Map<String, String> headers = new LinkedHashMap<>();
        for (String name : Collections.list(http.getHeaderNames())) {
            headers.put(name.toLowerCase(Locale.ROOT), String.join(", ", Collections.list(http.getHeaders(name))));
        }
        byte[] body = http.getInputStream().readAllBytes();
        URI uri = request.uri();
        return new ApiRequest(request.method().name(), uri.getRawPath(), ApiRequest.parseQuery(uri.getRawQuery()), headers,
                body.length > 0 ? body : null, IdentityReader.fromHeaders(headers));
    }

    public static ServerResponse toResponse(ApiResponse resp) {
        ServerResponse.BodyBuilder out = ServerResponse.status(resp.status());
        for (Map.Entry<String, String> h : resp.headers().entrySet()) out.header(h.getKey(), h.getValue());
        return resp.hasBody() ? out.body(resp.text().getBytes(StandardCharsets.UTF_8)) : out.build();
    }

    /** Route per i percorsi delle operazioni dell'Api e una route finale per i percorsi sconosciuti (404 uniforme). */
    public static RouterFunction<ServerResponse> routes(Api api) {
        HandlerFunction<ServerResponse> handler = request -> toResponse(api.handle(toRequest(request)));
        Set<String> paths = new LinkedHashSet<>();
        for (Route r : api.routes()) paths.add(api.basePath() + r.spec().path());
        RouterFunctions.Builder builder = RouterFunctions.route();
        for (String p : paths) builder.route(RequestPredicates.path(p), handler);
        return builder.route(RequestPredicates.all(), handler).build(); // percorsi sconosciuti: 404 del nucleo, come gli altri adattatori
    }
}
'''

FILES = {"Json.java": JSON, "JsonSchema.java": SCHEMA, "ApiRequest.java": REQUEST, "ApiResponse.java": RESPONSE,
         "ApiError.java": ERROR, "Errors.java": ERRORS, "Identity.java": TYPES, "Call.java": CALL, "Handler.java": HANDLER,
         "Controller.java": CONTROLLER, "IdentityReader.java": IDENTITY, "Spec.java": SPEC, "Route.java": ROUTE,
         "Api.java": ROUTER, "ApiData.java": DATA, "Convert.java": CONVERT, "LambdaAdapter.java": LAMBDA,
         "HttpServerAdapter.java": JDK_HTTP, "SpringAdapter.java": SPRING}


def jstr(s: str) -> str:
    """Letterale stringa Java."""
    out = []
    for ch in s:
        if ch == "\\":
            out.append("\\\\")
        elif ch == '"':
            out.append('\\"')
        elif ch == "\n":
            out.append("\\n")
        elif ord(ch) < 0x20:
            out.append(f"\\u{ord(ch):04x}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def files(api_pkg: str, model_pkg: str, sql: bool, mongo: bool, claims: Dict, headers: Dict) -> Dict[str, str]:
    out = {}
    for name, text in FILES.items():
        t = text.replace("__PKG__", api_pkg).replace("__MGEN__", model_pkg + ".generated")
        t = (t.replace("__CLAIM_SUBJECT__", jstr(claims["subject"])).replace("__CLAIM_TENANT__", jstr(claims["tenant"]))
             .replace("__CLAIM_SCOPES__", ", ".join(jstr(s) for s in claims["scopes"]))
             .replace("__HEADER_SUBJECT__", jstr(headers["subject"])).replace("__HEADER_TENANT__", jstr(headers["tenant"]))
             .replace("__HEADER_SCOPES__", jstr(headers["scopes"])))
        out[name] = _strip_block(strip_sql(t, sql), "mongo", mongo)
    return out
