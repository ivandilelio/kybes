"""Moduli comuni delle API C# (namespace <ApiRouter>, cartella src/api/generated): JSON, validatore, router e middleware,
accesso ai dati, adattatori per AWS Lambda (handler a stream) e ASP.NET Core (minimal API).

JSON e validazione sono scritti qui, con le stesse regole e gli stessi testi di Python, TypeScript e Java.
__NS__ è il namespace delle API, __MODEL__ quello del modello.
"""
from __future__ import annotations

from typing import Dict

from runtime_api_typescript import _strip_block
from sqlonly import strip_sql

USINGS = """#nullable enable
using System;
using System.Collections;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Linq;
using System.Numerics;
using System.Text;
using System.Text.RegularExpressions;
using System.Threading;
using System.Threading.Tasks;
"""

JSON = r'''
namespace __NS__;

/// <summary>Testo che non è JSON valido.</summary>
public sealed class JsonError : Exception
{
    public JsonError(string message) : base(message) { }
}

/// <summary>
/// JSON senza dipendenze, come lo legge e lo scrive il nucleo delle API: oggetti come Dictionary, array come List,
/// interi come long (BigInteger oltre i 64 bit), gli altri numeri come double. Rifiuta NaN e Infinity.
/// </summary>
public static class Json
{
    public static object? Parse(string text)
    {
        var p = new Parser(text);
        p.Ws();
        var value = p.Value(0);
        p.Ws();
        if (p.I != text.Length) throw new JsonError("caratteri dopo il valore JSON");
        return value;
    }

    public static string Write(object? value)
    {
        var sb = new StringBuilder();
        Write(sb, value);
        return sb.ToString();
    }

    private static void Write(StringBuilder sb, object? v)
    {
        switch (v)
        {
            case null:
                sb.Append("null");
                break;
            case string s:
                Quote(sb, s);
                break;
            case bool b:
                sb.Append(b ? "true" : "false");
                break;
            case double d:
                if (double.IsNaN(d) || double.IsInfinity(d)) throw new JsonError("numero non rappresentabile in JSON");
                sb.Append(d.ToString("R", CultureInfo.InvariantCulture));
                break;
            case long or int or short or BigInteger or decimal:
                sb.Append(Convert.ToString(v, CultureInfo.InvariantCulture));
                break;
            case IDictionary m:
                sb.Append('{');
                var first = true;
                foreach (DictionaryEntry e in m)
                {
                    if (!first) sb.Append(',');
                    first = false;
                    Quote(sb, e.Key.ToString()!);
                    sb.Append(':');
                    Write(sb, e.Value);
                }
                sb.Append('}');
                break;
            case IEnumerable list:
                sb.Append('[');
                var head = true;
                foreach (var x in list)
                {
                    if (!head) sb.Append(',');
                    head = false;
                    Write(sb, x);
                }
                sb.Append(']');
                break;
            default:
                Quote(sb, v.ToString()!);
                break;
        }
    }

    private static void Quote(StringBuilder sb, string s)
    {
        sb.Append('"');
        foreach (var c in s)
        {
            switch (c)
            {
                case '"': sb.Append("\\\""); break;
                case '\\': sb.Append("\\\\"); break;
                case '\n': sb.Append("\\n"); break;
                case '\r': sb.Append("\\r"); break;
                case '\t': sb.Append("\\t"); break;
                default:
                    if (c < 0x20) sb.Append("\\u").Append(((int)c).ToString("x4", CultureInfo.InvariantCulture));
                    else sb.Append(c);
                    break;
            }
        }
        sb.Append('"');
    }

    private sealed class Parser
    {
        private readonly string s;
        public int I;

        public Parser(string s) { this.s = s; }

        public void Ws()
        {
            while (I < s.Length && " \t\r\n".IndexOf(s[I]) >= 0) I++;
        }

        private char Peek()
        {
            if (I >= s.Length) throw new JsonError("fine inattesa del testo JSON");
            return s[I];
        }

        private void Expect(char c)
        {
            if (Peek() != c) throw new JsonError($"atteso '{c}' alla posizione {I}");
            I++;
        }

        public object? Value(int depth)
        {
            if (depth > 512) throw new JsonError("annidamento eccessivo");
            var c = Peek();
            if (c == '{') return ParseObject(depth);
            if (c == '[') return ParseArray(depth);
            if (c == '"') return ParseString();
            if (string.CompareOrdinal(s, I, "true", 0, 4) == 0) return Literal(4, true);
            if (string.CompareOrdinal(s, I, "false", 0, 5) == 0) return Literal(5, false);
            if (string.CompareOrdinal(s, I, "null", 0, 4) == 0) return Literal(4, null);
            return ParseNumber();
        }

        private object? Literal(int length, object? value)
        {
            I += length;
            return value;
        }

        private Dictionary<string, object?> ParseObject(int depth)
        {
            var o = new Dictionary<string, object?>();
            I++;
            Ws();
            if (Peek() == '}')
            {
                I++;
                return o;
            }
            while (true)
            {
                Ws();
                if (Peek() != '"') throw new JsonError($"attesa una chiave alla posizione {I}");
                var key = ParseString();
                Ws();
                Expect(':');
                Ws();
                o[key] = Value(depth + 1);
                Ws();
                if (Peek() == '}')
                {
                    I++;
                    return o;
                }
                Expect(',');
            }
        }

        private List<object?> ParseArray(int depth)
        {
            var o = new List<object?>();
            I++;
            Ws();
            if (Peek() == ']')
            {
                I++;
                return o;
            }
            while (true)
            {
                Ws();
                o.Add(Value(depth + 1));
                Ws();
                if (Peek() == ']')
                {
                    I++;
                    return o;
                }
                Expect(',');
            }
        }

        private string ParseString()
        {
            var sb = new StringBuilder();
            I++;
            while (true)
            {
                var c = Peek();
                I++;
                if (c == '"') return sb.ToString();
                if (c < 0x20) throw new JsonError("carattere di controllo in una stringa");
                if (c != '\\')
                {
                    sb.Append(c);
                    continue;
                }
                var e = Peek();
                I++;
                switch (e)
                {
                    case '"': case '\\': case '/': sb.Append(e); break;
                    case 'b': sb.Append('\b'); break;
                    case 'f': sb.Append('\f'); break;
                    case 'n': sb.Append('\n'); break;
                    case 'r': sb.Append('\r'); break;
                    case 't': sb.Append('\t'); break;
                    case 'u':
                        if (I + 4 > s.Length) throw new JsonError("escape unicode incompleto");
                        if (!int.TryParse(s.AsSpan(I, 4), NumberStyles.AllowHexSpecifier, CultureInfo.InvariantCulture, out var code))
                            throw new JsonError("escape unicode non valido");
                        sb.Append((char)code);
                        I += 4;
                        break;
                    default: throw new JsonError("escape non valido");
                }
            }
        }

        private object ParseNumber()
        {
            var start = I;
            if (Peek() == '-') I++;
            if (Peek() == '0') I++;
            else Digits();
            var integral = true;
            if (I < s.Length && s[I] == '.')
            {
                integral = false;
                I++;
                Digits();
            }
            if (I < s.Length && (s[I] == 'e' || s[I] == 'E'))
            {
                integral = false;
                I++;
                if (Peek() == '+' || Peek() == '-') I++;
                Digits();
            }
            var text = s[start..I];
            if (integral)
            {
                var big = BigInteger.Parse(text, CultureInfo.InvariantCulture);
                return big >= long.MinValue && big <= long.MaxValue ? (long)big : big;
            }
            var d = double.Parse(text, CultureInfo.InvariantCulture);
            if (double.IsInfinity(d)) throw new JsonError("numero fuori intervallo");
            return d;
        }

        private void Digits()
        {
            var start = I;
            while (I < s.Length && s[I] >= '0' && s[I] <= '9') I++;
            if (I == start) throw new JsonError($"cifra attesa alla posizione {I}");
        }
    }
}
'''

SCHEMA = r'''
namespace __NS__;

/// <summary>Valore di un parametro convertito nel tipo dello schema, oppure la regola violata.</summary>
public sealed record Coerced(object? Value, string? Error);

/// <summary>
/// Validatore del sottoinsieme di JSON Schema (OpenAPI 3.0) usato dal contratto delle API: stesse regole e stessi
/// testi in tutti i linguaggi. Per ogni campo si riporta la prima regola violata.
/// </summary>
public static class JsonSchema
{
    private static readonly Regex Uuid = new("^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$");
    private static readonly Regex Date = new("^[0-9]{4}-[0-9]{2}-[0-9]{2}$");
    private static readonly Regex DateTimeRe = new(@"^([0-9]{4}-[0-9]{2}-[0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})(\.[0-9]{1,9})?(Z|[+-]([0-9]{2}):([0-9]{2}))$");
    private static readonly Regex Integer = new("^-?[0-9]+$");
    private static readonly Regex NumberText = new(@"^-?[0-9]+(\.[0-9]+)?([eE][+-]?[0-9]+)?$");

    /// <summary>Numero nel testo di una regola: gli interi senza decimali.</summary>
    public static string Num(object x) => Convert.ToString(x, CultureInfo.InvariantCulture)!;

    private static bool ValidDate(string s) =>
        DateOnly.TryParseExact(s, "yyyy-MM-dd", CultureInfo.InvariantCulture, DateTimeStyles.None, out _);

    public static bool CheckFormat(string fmt, string s)
    {
        if (fmt == "uuid") return Uuid.IsMatch(s);
        if (fmt == "date") return Date.IsMatch(s) && ValidDate(s);
        var m = DateTimeRe.Match(s);
        if (!m.Success || !ValidDate(m.Groups[1].Value)) return false;
        if (int.Parse(m.Groups[2].Value) > 23 || int.Parse(m.Groups[3].Value) > 59 || int.Parse(m.Groups[4].Value) > 59) return false;
        return m.Groups[6].Value == "Z" || (int.Parse(m.Groups[7].Value) <= 23 && int.Parse(m.Groups[8].Value) <= 59);
    }

    /// <summary>Tipo JSON di un valore non nullo (il nullo lo gestisce Validate).</summary>
    public static string TypeOf(object? v) => v switch
    {
        bool => "boolean",
        long or BigInteger => "integer",
        double d => d == Math.Floor(d) ? "integer" : "number",
        string => "string",
        IList => "array",
        IDictionary => "object",
        _ => "unknown",
    };

    private static BigInteger Big(object x) => x is BigInteger b ? b : new BigInteger((long)x);

    /// <summary>Confronto tra numeri JSON: interi esatti, altrimenti in virgola mobile.</summary>
    public static int Compare(object a, object b)
    {
        if (a is double || b is double) return Convert.ToDouble(a, CultureInfo.InvariantCulture).CompareTo(Convert.ToDouble(b, CultureInfo.InvariantCulture));
        return Big(a).CompareTo(Big(b));
    }

    private static bool Same(object? a, object? b)
    {
        if (TypeOf(a) != TypeOf(b)) return false;
        if (TypeOf(a) is "integer" or "number") return Compare(a!, b!) == 0;
        return Json.Write(a) == Json.Write(b);
    }

    private static int Int(object? x) => Convert.ToInt32(x, CultureInfo.InvariantCulture);

    /// <summary>Aggiunge a errors {percorso: regola} le violazioni di value; un solo errore per percorso.</summary>
    public static void Validate(IReadOnlyDictionary<string, object?> schema, object? value, string path, IDictionary<string, string> errors)
    {
        var where = path.Length == 0 ? "body" : path;
        if (errors.ContainsKey(where)) return;
        if (value is null)
        {
            if (!Equals(schema.GetValueOrDefault("nullable"), true) && schema.ContainsKey("type")) errors[where] = "nullo non ammesso";
            return;
        }
        var t = TypeOf(value);
        var want = schema.GetValueOrDefault("type") as string;
        if (want is not null && !(t == want || (want == "number" && t == "integer")))
        {
            errors[where] = "tipo atteso: " + want;
            return;
        }
        if (schema.GetValueOrDefault("enum") is IList options && !options.Cast<object?>().Any(o => Same(o, value)))
        {
            errors[where] = "valore non ammesso";
            return;
        }
        switch (t)
        {
            case "string":
                var s = (string)value;
                var n = s.EnumerateRunes().Count();
                if (schema.ContainsKey("minLength") && n < Int(schema["minLength"])) errors[where] = "lunghezza minima " + Num(schema["minLength"]!);
                else if (schema.ContainsKey("maxLength") && n > Int(schema["maxLength"])) errors[where] = "lunghezza massima " + Num(schema["maxLength"]!);
                else if (schema.ContainsKey("pattern") && !Regex.IsMatch(s, (string)schema["pattern"]!)) errors[where] = "formato non valido";
                else if (schema.ContainsKey("format") && !CheckFormat((string)schema["format"]!, s)) errors[where] = "formato " + schema["format"];
                break;
            case "integer":
            case "number":
                if (schema.ContainsKey("minimum") && Compare(value, schema["minimum"]!) < 0) errors[where] = "valore minimo " + Num(schema["minimum"]!);
                else if (schema.ContainsKey("maximum") && Compare(value, schema["maximum"]!) > 0) errors[where] = "valore massimo " + Num(schema["maximum"]!);
                break;
            case "array":
                var a = (IList)value;
                if (schema.ContainsKey("minItems") && a.Count < Int(schema["minItems"])) errors[where] = $"almeno {Num(schema["minItems"]!)} elementi";
                else if (schema.ContainsKey("maxItems") && a.Count > Int(schema["maxItems"])) errors[where] = $"al massimo {Num(schema["maxItems"]!)} elementi";
                else if (schema.GetValueOrDefault("items") is IReadOnlyDictionary<string, object?> items)
                {
                    for (var i = 0; i < a.Count; i++) Validate(items, a[i], $"{path}[{i}]", errors);
                }
                break;
            case "object":
                var o = (IReadOnlyDictionary<string, object?>)value;
                var props = schema.GetValueOrDefault("properties") as IReadOnlyDictionary<string, object?> ?? new Dictionary<string, object?>();
                var prefix = path.Length == 0 ? "" : path + ".";
                foreach (var name in (schema.GetValueOrDefault("required") as IList ?? new List<object?>()).Cast<string>())
                {
                    if (!o.ContainsKey(name)) errors.TryAdd(prefix + name, "obbligatorio");
                }
                foreach (var p in props)
                {
                    if (o.ContainsKey(p.Key)) Validate((IReadOnlyDictionary<string, object?>)p.Value!, o[p.Key], prefix + p.Key, errors);
                }
                var extra = schema.GetValueOrDefault("additionalProperties", true);
                foreach (var name in o.Keys)
                {
                    if (props.ContainsKey(name)) continue;
                    if (Equals(extra, false)) errors.TryAdd(prefix + name, "non ammesso");
                    else if (extra is IReadOnlyDictionary<string, object?> sub) Validate(sub, o[name], prefix + name, errors);
                }
                break;
        }
    }

    /// <summary>Valore di un parametro di path o query (testo) nel tipo dello schema.</summary>
    public static Coerced Coerce(IReadOnlyDictionary<string, object?> schema, IReadOnlyList<string> raw)
    {
        var type = schema.GetValueOrDefault("type") as string;
        if (type == "array")
        {
            var items = schema.GetValueOrDefault("items") as IReadOnlyDictionary<string, object?> ?? new Dictionary<string, object?>();
            var output = new List<object?>();
            foreach (var r in raw)
            {
                var c = Coerce(items, new[] { r });
                if (c.Error is not null) return new Coerced(null, c.Error);
                output.Add(c.Value);
            }
            return new Coerced(output, null);
        }
        if (raw.Count != 1) return new Coerced(null, "un solo valore");
        var text = raw[0];
        if (type == "integer")
        {
            if (!Integer.IsMatch(text)) return new Coerced(null, "tipo atteso: integer");
            var big = BigInteger.Parse(text, CultureInfo.InvariantCulture);
            return new Coerced(big >= long.MinValue && big <= long.MaxValue ? (long)big : big, null);
        }
        if (type == "number")
            return NumberText.IsMatch(text) ? new Coerced(double.Parse(text, CultureInfo.InvariantCulture), null) : new Coerced(null, "tipo atteso: number");
        if (type == "boolean")
            return text is "true" or "false" ? new Coerced(text == "true", null) : new Coerced(null, "tipo atteso: boolean");
        return new Coerced(text, null);
    }
}
'''

HTTP = r'''
namespace __NS__;

/// <summary>Chi chiama: claim già verificati dal gateway (mai il token grezzo).</summary>
public sealed record Identity(string? Subject, string? Tenant, IReadOnlySet<string> Scopes, IReadOnlyDictionary<string, object?> Claims)
{
    public static Identity Anonymous() => new(null, null, new HashSet<string>(), new Dictionary<string, object?>());
}

/// <summary>
/// Richiesta HTTP indipendente dal runtime (Lambda, ASP.NET Core): nomi degli header in minuscolo, corpo grezzo (null se
/// assente), identità dai claim già verificati dal gateway (null se assente).
/// </summary>
public sealed record ApiRequest(string Method, string Path, IReadOnlyDictionary<string, List<string>> Query,
    IReadOnlyDictionary<string, string> Headers, byte[]? Body, Identity? Identity)
{
    /// <summary>Query string grezza (a=1&amp;b=x%20y, con o senza '?') -> {nome: valori}.</summary>
    public static Dictionary<string, List<string>> ParseQuery(string? raw)
    {
        var output = new Dictionary<string, List<string>>();
        foreach (var part in (raw ?? "").TrimStart('?').Split('&'))
        {
            if (part.Length == 0) continue;
            var eq = part.IndexOf('=');
            var name = Decode(eq < 0 ? part : part[..eq], true);
            var value = Decode(eq < 0 ? "" : part[(eq + 1)..], true);
            if (!output.TryGetValue(name, out var values)) output[name] = values = new List<string>();
            values.Add(value);
        }
        return output;
    }

    /// <summary>Percent-decoding UTF-8; form: '+' vale spazio (query), altrimenti resta '+' (percorso).</summary>
    public static string Decode(string s, bool form) => Uri.UnescapeDataString(form ? s.Replace('+', ' ') : s);
}

/// <summary>Risposta HTTP: stato, corpo JSON (HasBody falso per 204 e simili) e header.</summary>
public sealed class ApiResponse
{
    public ApiResponse(int status, object? body, IDictionary<string, string> headers, bool hasBody)
    {
        Status = status;
        Body = body;
        Headers = new Dictionary<string, string>(headers);
        HasBody = hasBody;
    }

    public int Status { get; }
    public object? Body { get; }
    public Dictionary<string, string> Headers { get; }
    public bool HasBody { get; }

    /// <summary>Risposta senza corpo costruita dal service.</summary>
    public static ApiResponse Reply(int status) => new(status, null, new Dictionary<string, string>(), false);

    /// <summary>Risposta JSON costruita dal service (stato proprio, header propri facoltativi).</summary>
    public static ApiResponse Reply(int status, object? body, IDictionary<string, string>? headers = null) =>
        new(status, body, headers ?? new Dictionary<string, string> { ["content-type"] = "application/json" }, true);

    /// <summary>Corpo come testo JSON ("" senza corpo).</summary>
    public string Text() => HasBody ? Json.Write(Body) : "";
}

/// <summary>Errore applicativo con esito HTTP: Kind è una chiave di Errors.Status, Fields {campo: regola}.</summary>
public sealed class ApiError : Exception
{
    public ApiError(string kind, string code, IDictionary<string, string>? fields = null) : base(code)
    {
        Kind = kind;
        Code = code;
        Fields = new Dictionary<string, string>(fields ?? new Dictionary<string, string>());
    }

    public string Kind { get; }
    public string Code { get; }
    public Dictionary<string, string> Fields { get; }
}

/// <summary>Errore -> stato HTTP; il messaggio pubblico non contiene dettagli (che restano nei log, con il correlationId).</summary>
public static class Errors
{
    public static readonly IReadOnlyDictionary<string, int> Status = new Dictionary<string, int>
    {
        ["VALIDATION"] = 400, ["AUTH"] = 401, ["FORBIDDEN"] = 403, ["NOT_FOUND"] = 404, ["METHOD_NOT_ALLOWED"] = 405,
        ["CONFLICT"] = 409, ["UNSUPPORTED_MEDIA_TYPE"] = 415, ["UNPROCESSABLE"] = 422, ["INTERNAL"] = 500, ["TRANSIENT"] = 503,
    };

    public static readonly IReadOnlyDictionary<string, string> Message = new Dictionary<string, string>
    {
        ["VALIDATION"] = "Richiesta non valida", ["AUTH"] = "Autenticazione richiesta", ["FORBIDDEN"] = "Operazione non consentita",
        ["NOT_FOUND"] = "Risorsa non trovata", ["METHOD_NOT_ALLOWED"] = "Metodo non ammesso", ["CONFLICT"] = "Conflitto con lo stato attuale",
        ["UNSUPPORTED_MEDIA_TYPE"] = "Serve un corpo application/json", ["UNPROCESSABLE"] = "Dati non accettati dal modello",
        ["INTERNAL"] = "Errore interno", ["TRANSIENT"] = "Servizio temporaneamente non disponibile",
    };

    /// <summary>{"error": {"code", "message", "correlationId", "fields"?}}</summary>
    public static Dictionary<string, object?> ErrorBody(string kind, string code, string cid, IDictionary<string, string>? fields)
    {
        var error = new Dictionary<string, object?> { ["code"] = code, ["message"] = Message[kind], ["correlationId"] = cid };
        if (fields is { Count: > 0 }) error["fields"] = fields;
        return new Dictionary<string, object?> { ["error"] = error };
    }
}

/// <summary>Input già validato di un'operazione, passato al controller generato o al metodo del service.</summary>
public sealed record Call(string Operation, IReadOnlyDictionary<string, object?> Path, IReadOnlyDictionary<string, object?> Query,
    object? Body, Identity Identity, string CorrelationId, string? Tenant);

/// <summary>Esegue un'operazione: restituisce il corpo JSON della risposta (stato del contratto) o un ApiResponse.</summary>
public delegate Task<object?> Handler(Call call);
'''

IDENTITY = r'''
namespace __NS__;

/// <summary>
/// Identità dai claim già verificati dal gateway: requestContext.authorizer (Lambda) o header impostati dal gateway.
/// Il servizio non verifica il token: deve essere raggiungibile solo dal gateway (rete privata, VPC link), che
/// sovrascrive gli header di identità a ogni richiesta.
/// </summary>
public static class IdentityReader
{
    public const string ClaimSubject = __CLAIM_SUBJECT__;
    public const string ClaimTenant = __CLAIM_TENANT__;
    public static readonly IReadOnlyList<string> ClaimScopes = new[] { __CLAIM_SCOPES__ };
    public const string HeaderSubject = __HEADER_SUBJECT__;
    public const string HeaderTenant = __HEADER_TENANT__;
    public const string HeaderScopes = __HEADER_SCOPES__;

    /// <summary>Scope da un claim: lista, "a b", "a,b" o "[a b]" (forma degli array nei claim di API Gateway HTTP API).</summary>
    public static List<string> ScopesOf(object? value)
    {
        if (value is null) return new List<string>();
        if (value is IList list) return list.Cast<object?>().Select(x => Convert.ToString(x, CultureInfo.InvariantCulture)!).ToList();
        var text = value.ToString()!.Trim();
        if (text.StartsWith('[') && text.EndsWith(']')) text = text[1..^1];
        return text.Replace(',', ' ').Split((char[]?)null, StringSplitOptions.RemoveEmptyEntries).ToList();
    }

    private static string? Opt(object? v) => v is null || Equals(v, "") ? null : v.ToString();

    public static Identity FromClaims(IReadOnlyDictionary<string, object?> claims)
    {
        var scopes = new HashSet<string>();
        foreach (var name in ClaimScopes) scopes.UnionWith(ScopesOf(claims.GetValueOrDefault(name)));
        return new Identity(Opt(claims.GetValueOrDefault(ClaimSubject)), Opt(claims.GetValueOrDefault(ClaimTenant)), scopes,
            new Dictionary<string, object?>(claims));
    }

    /// <summary>API Gateway: HTTP API (authorizer.jwt.claims o authorizer.lambda) o REST API (authorizer.claims o contesto).</summary>
    public static Identity? FromLambda(IReadOnlyDictionary<string, object?> ev)
    {
        var context = ev.GetValueOrDefault("requestContext") as IReadOnlyDictionary<string, object?>;
        if (context?.GetValueOrDefault("authorizer") is not IReadOnlyDictionary<string, object?> auth) return null;
        var claims = (auth.GetValueOrDefault("jwt") as IReadOnlyDictionary<string, object?>)?.GetValueOrDefault("claims")
            ?? auth.GetValueOrDefault("lambda") ?? auth.GetValueOrDefault("claims") ?? auth;
        if (claims is string s) claims = Json.Parse(s); // authorizer Lambda di REST API: claim come JSON
        return FromClaims((IReadOnlyDictionary<string, object?>)claims!);
    }

    /// <summary>Kubernetes dietro il gateway: claim copiati negli header dal parameter mapping del gateway.</summary>
    public static Identity? FromHeaders(IReadOnlyDictionary<string, string> headers)
    {
        if (!headers.TryGetValue(HeaderSubject, out var subject)) return null;
        var claims = new Dictionary<string, object?> { [ClaimSubject] = subject };
        if (headers.TryGetValue(HeaderTenant, out var tenant)) claims[ClaimTenant] = tenant;
        if (headers.TryGetValue(HeaderScopes, out var scopes)) claims[ClaimScopes[0]] = scopes;
        return FromClaims(claims);
    }
}
'''

ROUTER = r'''using __MODEL__;
// kybes:sql-begin
using System.Data.Common;
// kybes:sql-end
// kybes:mongo-begin
using MongoDB.Driver;
// kybes:mongo-end

namespace __NS__;

// Router e middleware delle API: correlationId, percorso e metodo, identità e scope, validazione, errori.
// Ordine per ogni richiesta (uguale in tutti i linguaggi):
//   1. correlationId dall'header x-correlation-id (se valido) o nuovo;
//   2. operazione dal percorso (i segmenti fissi vincono sui parametri) e dal metodo: 404 o 405;
//   3. identità obbligatoria per le operazioni protette (401) e scope richiesti (403);
//   4. parametri di path e query: tipi, regole, parametri sconosciuti (400);
//   5. corpo: application/json (415), JSON valido e conforme allo schema (400);
//   6. controller o metodo del service; errori del modello e del database -> 404, 409, 422, 503; il resto -> 500.

/// <summary>Parametro di path o query.</summary>
public sealed record Param(string Name, string In, bool Required, IReadOnlyDictionary<string, object?> Schema);

/// <summary>Operazione del contratto: percorso, metodo, contesto, scope, schemi di parametri e corpo.</summary>
public sealed record Spec(string Id, string Method, string Path, string Context, string Kind, string? Table, string? Arg, int Status,
    bool Secured, IReadOnlyList<string> Scopes, IReadOnlyList<Param> Params, IReadOnlyDictionary<string, object?>? Body, bool BodyRequired)
{
    /// <summary>Spec dalla sua forma JSON (incorporata nel codice generato).</summary>
    public static Spec Of(string json)
    {
        var m = (IReadOnlyDictionary<string, object?>)Json.Parse(json)!;
        var ps = ((IList)m["params"]!).Cast<IReadOnlyDictionary<string, object?>>()
            .Select(p => new Param((string)p["name"]!, (string)p["in"]!, (bool)p["required"]!, (IReadOnlyDictionary<string, object?>)p["schema"]!)).ToList();
        return new Spec((string)m["id"]!, (string)m["method"]!, (string)m["path"]!, (string)m["context"]!, (string)m["kind"]!,
            m["table"] as string, m["arg"] as string, (int)(long)m["status"]!, (bool)m["secured"]!,
            ((IList)m["scopes"]!).Cast<string>().ToList(), ps, m["body"] as IReadOnlyDictionary<string, object?>, (bool)m["bodyRequired"]!);
    }
}

/// <summary>Un'operazione con il suo handler e i segmenti del percorso.</summary>
public sealed class Route
{
    private readonly string[] segments;

    public Route(Spec spec, Handler? handler)
    {
        Spec = spec;
        Handler = handler;
        segments = spec.Path.Split('/', StringSplitOptions.RemoveEmptyEntries);
    }

    public Spec Spec { get; }
    public Handler? Handler { get; }

    /// <summary>Parametri di percorso se parts corrisponde, altrimenti null.</summary>
    public Dictionary<string, string>? Match(IReadOnlyList<string> parts)
    {
        if (parts.Count != segments.Length) return null;
        var output = new Dictionary<string, string>();
        for (var i = 0; i < parts.Count; i++)
        {
            var seg = segments[i];
            if (seg.StartsWith('{')) output[seg[1..^1]] = parts[i];
            else if (seg != parts[i]) return null;
        }
        return output;
    }

    /// <summary>I segmenti fissi vincono sui parametri, da sinistra a destra.</summary>
    public string Rank => string.Concat(segments.Select(s => s.StartsWith('{') ? "1" : "0"));
}

/// <summary>Le operazioni del contratto con i loro handler: HandleAsync(ApiRequest) -> ApiResponse.</summary>
public sealed class ApiRouter
{
    private static readonly Regex Cid = new("^[A-Za-z0-9._-]{1,128}$");
    private static readonly HashSet<string> PagingFields = new() { "limit", "sort", "cursor" };
    private static readonly HashSet<string> Shown = new() { "VALIDATION", "CONFLICT", "UNPROCESSABLE" };
    private static readonly UTF8Encoding Utf8 = new(false, true);

    /// <summary>Errori inattesi (500): dettagli solo nei log, con il correlationId. Di default su stderr.</summary>
    public static Action<string, Exception> Log { get; set; } = (cid, e) =>
        Console.Error.WriteLine(Json.Write(new Dictionary<string, object?> { ["level"] = "error", ["msg"] = "api: errore inatteso", ["correlationId"] = cid, ["cause"] = e.ToString() }));

    public ApiRouter(IEnumerable<Spec> specs, IReadOnlyDictionary<string, Handler> handlers, string basePath = "")
    {
        Routes = specs.Select(s => new Route(s, handlers.GetValueOrDefault(s.Id))).OrderBy(r => r.Rank, StringComparer.Ordinal).ToList();
        BasePath = basePath.TrimEnd('/');
    }

    public IReadOnlyList<Route> Routes { get; }
    public string BasePath { get; }

    /// <summary>Errore del modello, del database o inatteso -> errore dell'API.</summary>
    public static ApiError MapError(Exception err)
    {
        if (err is ApiError api) return api;
        if (err is ModelValidationException mv)
        {
            var fields = new Dictionary<string, string>(mv.Fields);
            if (fields.Count > 0 && fields.Keys.All(PagingFields.Contains)) return new ApiError("VALIDATION", "INVALID_PAGE", fields);
            if (fields.Count > 0 && fields.Values.All(v => v == "record collegati")) return new ApiError("CONFLICT", "RELATED_RECORDS", fields);
            return new ApiError("UNPROCESSABLE", "MODEL_RULE", fields);
        }
        if (err is TenantException) return new ApiError("FORBIDDEN", "TENANT_REQUIRED");
        if (err is KeyNotFoundException) return new ApiError("NOT_FOUND", "RECORD_NOT_FOUND");
        // kybes:mongo-begin
        for (Exception? e = err; e is not null; e = e.InnerException)
        {
            if (e is MongoException && e.Message.Contains("E11000", StringComparison.Ordinal)) return new ApiError("CONFLICT", "DUPLICATE");
        }
        // kybes:mongo-end
        // kybes:sql-begin
        for (Exception? e = err; e is not null; e = e.InnerException)
        {
            if (e is DbException db && (db.SqlState ?? "").StartsWith("23", StringComparison.Ordinal)) return new ApiError("CONFLICT", "CONSTRAINT");
        }
        if (UnitOfWork.IsRetryable(err)) return new ApiError("TRANSIENT", "RETRY_LATER");
        // kybes:sql-end
        return new ApiError("INTERNAL", "UNEXPECTED");
    }

    public async Task<ApiResponse> HandleAsync(ApiRequest req)
    {
        var given = req.Headers.GetValueOrDefault("x-correlation-id") ?? "";
        var cid = Cid.IsMatch(given) ? given : Guid.NewGuid().ToString();
        ApiResponse resp;
        try
        {
            resp = await DispatchAsync(req, cid);
        }
        catch (Exception exc)
        {
            var err = MapError(exc);
            if (err.Kind == "INTERNAL") Log(cid, exc);
            var headers = new Dictionary<string, string> { ["content-type"] = "application/json" };
            var fields = new Dictionary<string, string>(err.Fields);
            if (err.Kind == "METHOD_NOT_ALLOWED")
            {
                headers["allow"] = fields["allow"];
                fields.Remove("allow");
            }
            resp = new ApiResponse(Errors.Status[err.Kind], Errors.ErrorBody(err.Kind, err.Code, cid, Shown.Contains(err.Kind) ? fields : null), headers, true);
        }
        resp.Headers["x-correlation-id"] = cid;
        return resp;
    }

    private (Route Route, Dictionary<string, string> Params) Find(ApiRequest req)
    {
        var path = req.Path;
        if (BasePath.Length > 0 && (path == BasePath || path.StartsWith(BasePath + "/", StringComparison.Ordinal))) path = path[BasePath.Length..];
        var parts = path.Split('/', StringSplitOptions.RemoveEmptyEntries).Select(p => ApiRequest.Decode(p, false)).ToList();
        var allowed = new SortedSet<string>(StringComparer.Ordinal);
        var method = req.Method.ToUpperInvariant();
        foreach (var r in Routes)
        {
            var found = r.Match(parts);
            if (found is null) continue;
            if (r.Spec.Method == method) return (r, found);
            allowed.Add(r.Spec.Method);
        }
        if (allowed.Count > 0) throw new ApiError("METHOD_NOT_ALLOWED", "METHOD_NOT_ALLOWED", new Dictionary<string, string> { ["allow"] = string.Join(", ", allowed) });
        throw new ApiError("NOT_FOUND", "ROUTE_NOT_FOUND");
    }

    private async Task<ApiResponse> DispatchAsync(ApiRequest req, string cid)
    {
        var (route, rawPath) = Find(req);
        var spec = route.Spec;
        var identity = req.Identity ?? Identity.Anonymous();
        if (spec.Secured && identity.Subject is null) throw new ApiError("AUTH", "IDENTITY_REQUIRED");
        if (!spec.Scopes.All(identity.Scopes.Contains)) throw new ApiError("FORBIDDEN", "SCOPE_REQUIRED");
        var errors = new Dictionary<string, string>();
        var pathValues = new Dictionary<string, object?>();
        var queryValues = new Dictionary<string, object?>();
        var known = spec.Params.Where(p => p.In == "query").Select(p => p.Name).ToHashSet();
        foreach (var name in req.Query.Keys)
        {
            if (!known.Contains(name)) errors[name] = "parametro sconosciuto";
        }
        foreach (var p in spec.Params)
        {
            var inPath = p.In == "path";
            IReadOnlyList<string>? raw = inPath ? new[] { rawPath[p.Name] } : req.Query.GetValueOrDefault(p.Name);
            if (raw is null)
            {
                if (p.Required) errors.TryAdd(p.Name, "obbligatorio");
                continue;
            }
            var c = JsonSchema.Coerce(p.Schema, raw);
            if (c.Error is not null)
            {
                errors.TryAdd(p.Name, c.Error);
                continue;
            }
            JsonSchema.Validate(p.Schema, c.Value, p.Name, errors);
            (inPath ? pathValues : queryValues)[p.Name] = c.Value;
        }
        object? body = null;
        var hasBody = req.Body is { Length: > 0 };
        if (spec.Body is null)
        {
            if (hasBody) errors.TryAdd("body", "corpo non ammesso");
        }
        else if (hasBody)
        {
            var ctype = (req.Headers.GetValueOrDefault("content-type") ?? "").Split(';')[0].Trim().ToLowerInvariant();
            if (ctype != "application/json") throw new ApiError("UNSUPPORTED_MEDIA_TYPE", "JSON_REQUIRED");
            try
            {
                body = Json.Parse(Utf8.GetString(req.Body!));
            }
            catch (Exception e) when (e is JsonError or DecoderFallbackException)
            {
                errors.TryAdd("body", "JSON non valido");
            }
            if (!errors.ContainsKey("body")) JsonSchema.Validate(spec.Body, body, "", errors);
        }
        else if (spec.BodyRequired)
        {
            errors.TryAdd("body", "obbligatorio");
        }
        if (errors.Count > 0) throw new ApiError("VALIDATION", "INVALID_REQUEST", errors);
        var result = await route.Handler!(new Call(spec.Id, pathValues, queryValues, body, identity, cid, identity.Tenant));
        if (result is ApiResponse r) return new ApiResponse(r.Status, r.Body, r.Headers, r.HasBody);
        if (spec.Status == 204) return ApiResponse.Reply(204);
        return ApiResponse.Reply(spec.Status, result);
    }
}
'''

DATA = r'''using __MODEL__;
// kybes:mongo-begin
using MongoDB.Driver;
// kybes:mongo-end

namespace __NS__;

/// <summary>
/// Accesso ai dati per i controller generati: letture con il tenant legato, scritture in una Unit of Work (tabelle SQL)
/// o in una transazione MongoDB (collection).
/// </summary>
public sealed class ApiData
{
    // kybes:sql-begin
    /// <summary>Un AppDbContext nuovo per operazione (per tenant, per le tabelle con tenancy schema o database).</summary>
    public Func<string?, AppDbContext>? SqlFor { get; init; }
    // kybes:sql-end
    // kybes:mongo-begin
    public IMongoClient? MongoClient { get; init; }
    public string? MongoDatabase { get; init; }
    /// <summary>Database per tenant, per le collection con tenancy database.</summary>
    public Func<string?, string>? MongoDatabaseFor { get; init; }
    // kybes:mongo-end

    // kybes:sql-begin
    private AppDbContext Sql(string? tenant)
    {
        if (SqlFor is null) throw new InvalidOperationException("ApiData: serve SqlFor per le tabelle SQL");
        return SqlFor(tenant);
    }

    public async Task<T> ReadAsync<T>(string? tenant, Func<AppDbContext, Task<T>> work)
    {
        var db = Sql(tenant);
        try
        {
            if (tenant is not null) db.BindTenant(tenant);
            return await work(db);
        }
        finally
        {
            await db.DisposeAsync();
        }
    }

    public async Task<T> WriteAsync<T>(IEnumerable<string> tables, string? tenant, Func<AppDbContext, Task<T>> work)
    {
        var db = Sql(tenant);
        try
        {
            return await UnitOfWork.RunAsync(db, (d, ct) => work(d), tables, tenant: tenant);
        }
        finally
        {
            await db.DisposeAsync();
        }
    }
    // kybes:sql-end

    // kybes:mongo-begin
    private string Database(string? tenant)
    {
        if (MongoClient is null) throw new InvalidOperationException("ApiData: serve MongoClient per le collection MongoDB");
        return MongoDatabaseFor is null ? MongoDatabase! : MongoDatabaseFor(tenant);
    }

    public Task<T> MongoReadAsync<T>(string? tenant, Func<MongoSession, Task<T>> work)
    {
        var database = Database(tenant);
        return work(MongoSession.Open(MongoClient!, database, tenant));
    }

    public Task<T> MongoWriteAsync<T>(string? tenant, Func<MongoSession, Task<T>> work)
    {
        var database = Database(tenant);
        return MongoSession.TransactionAsync(MongoClient!, database, work, tenant);
    }
    // kybes:mongo-end
}
'''

CONVERT = r'''using __MODEL__;

namespace __NS__;

/// <summary>
/// Conversioni tra il JSON delle API e i valori del modello (uguali in tutti i linguaggi): uuid, bigint e decimal come
/// stringhe; date "AAAA-MM-GG"; datetime ISO 8601 in UTC al millisecondo ("...Z"); json come testo nel modello.
/// </summary>
public static class ApiConvert
{
    private static readonly Regex Dt = new(@"^([0-9]{4})-([0-9]{2})-([0-9]{2})T([0-9]{2}):([0-9]{2}):([0-9]{2})(?:\.([0-9]{1,9}))?(Z|([+-])([0-9]{2}):([0-9]{2}))$");

    private static int I(Match m, int g) => int.Parse(m.Groups[g].Value, CultureInfo.InvariantCulture);

    public static Guid? ToUuid(object? v) => v is null ? null : Guid.Parse((string)v);
    public static int? ToInt(object? v) => v is null ? null : Convert.ToInt32(v, CultureInfo.InvariantCulture);
    public static long? ToBigint(object? v) => v is null ? null : long.Parse((string)v, CultureInfo.InvariantCulture);
    public static decimal? ToDecimal(object? v) => v is null ? null : decimal.Parse((string)v, NumberStyles.Number, CultureInfo.InvariantCulture);
    public static DateOnly? ToDate(object? v) => v is null ? null : DateOnly.ParseExact((string)v, "yyyy-MM-dd", CultureInfo.InvariantCulture);

    /// <summary>Data-ora validata (formato date-time) in UTC, al millisecondo.</summary>
    public static DateTimeOffset? ToDatetime(object? v)
    {
        if (v is null) return null;
        var m = Dt.Match((string)v);
        var ms = int.Parse(m.Groups[7].Value.PadRight(3, '0')[..3], CultureInfo.InvariantCulture);
        var offset = m.Groups[8].Value == "Z" ? TimeSpan.Zero : TimeSpan.FromMinutes((m.Groups[9].Value == "+" ? 1 : -1) * (I(m, 10) * 60 + I(m, 11)));
        return new DateTimeOffset(I(m, 1), I(m, 2), I(m, 3), I(m, 4), I(m, 5), I(m, 6), ms, offset).ToUniversalTime();
    }

    public static string? ToJsonText(object? v) => v is null ? null : Json.Write(v);

    /// <summary>Ogni elemento di una lista (parametro di query con op in) convertito con f.</summary>
    public static List<T> Each<T>(object? v, Func<object?, T> f) => ((IList)v!).Cast<object?>().Select(f).ToList();

    public static string? UuidText(Guid? v) => v?.ToString();
    public static string? Text(object? v) => v is null ? null : Convert.ToString(v, CultureInfo.InvariantCulture);

    public static string? DecimalText(decimal? v, int scale) =>
        v is null ? null : Math.Round(v.Value, scale, MidpointRounding.ToZero).ToString("F" + scale, CultureInfo.InvariantCulture);

    public static string? DateText(DateOnly? v) => v?.ToString("yyyy-MM-dd", CultureInfo.InvariantCulture);

    public static string? DatetimeText(DateTimeOffset? v) =>
        v?.UtcDateTime.ToString("yyyy-MM-dd'T'HH:mm:ss.fff'Z'", CultureInfo.InvariantCulture);

    public static object? JsonValue(string? v) => v is null ? null : Json.Parse(v);

    /// <summary>Pagina del modello nel formato del contratto.</summary>
    public static Dictionary<string, object?> PageJson<T>(Page<T> p, Func<T, Dictionary<string, object?>> conv) => new()
    {
        ["items"] = p.Items.Select(x => (object?)conv(x)).ToList(),
        ["nextCursor"] = p.NextCursor,
        ["limit"] = (long)p.Limit,
    };

    /// <summary>limit, cursor e sort della query come richiesta di pagina.</summary>
    public static PageRequest Request(IReadOnlyDictionary<string, object?> q) =>
        new(ToInt(q.GetValueOrDefault("limit")), q.GetValueOrDefault("cursor") as string, q.GetValueOrDefault("sort") as string);
}
'''

LAMBDA = r'''
namespace __NS__;

/// <summary>
/// Adattatore AWS Lambda (API Gateway HTTP API v2 e REST API v1) con handler a stream, senza pacchetti Amazon.Lambda:
/// public Task&lt;Stream&gt; FunctionHandler(Stream input) =&gt; LambdaAdapter.HandleAsync(ApiRouter, input);
/// </summary>
public static class LambdaAdapter
{
    public static ApiRequest ToRequest(IReadOnlyDictionary<string, object?> ev)
    {
        var headers = new Dictionary<string, string>();
        if (ev.GetValueOrDefault("headers") is IReadOnlyDictionary<string, object?> h)
        {
            foreach (var kv in h) headers[kv.Key.ToLowerInvariant()] = Convert.ToString(kv.Value, CultureInfo.InvariantCulture) ?? "";
        }
        byte[]? body = null;
        if (ev.GetValueOrDefault("body") is string raw)
            body = Equals(ev.GetValueOrDefault("isBase64Encoded"), true) ? Convert.FromBase64String(raw) : Encoding.UTF8.GetBytes(raw);
        Dictionary<string, List<string>> query;
        string method;
        string path;
        if (Equals(ev.GetValueOrDefault("version"), "2.0"))
        {
            var http = (IReadOnlyDictionary<string, object?>)((IReadOnlyDictionary<string, object?>)ev["requestContext"]!)["http"]!;
            method = (string)http["method"]!;
            path = OrRoot(ev.GetValueOrDefault("rawPath"));
            query = ApiRequest.ParseQuery(ev.GetValueOrDefault("rawQueryString") as string);
        }
        else
        {
            method = (string)ev["httpMethod"]!;
            path = OrRoot(ev.GetValueOrDefault("path"));
            query = new Dictionary<string, List<string>>();
            if (ev.GetValueOrDefault("multiValueQueryStringParameters") is IReadOnlyDictionary<string, object?> multi)
            {
                foreach (var kv in multi) query[kv.Key] = ((IList)kv.Value!).Cast<object?>().Select(x => Convert.ToString(x, CultureInfo.InvariantCulture)!).ToList();
            }
            else if (ev.GetValueOrDefault("queryStringParameters") is IReadOnlyDictionary<string, object?> single)
            {
                foreach (var kv in single) query[kv.Key] = new List<string> { Convert.ToString(kv.Value, CultureInfo.InvariantCulture)! };
            }
        }
        return new ApiRequest(method, path, query, headers, body, IdentityReader.FromLambda(ev));
    }

    private static string OrRoot(object? p) => p is string s && s.Length > 0 ? s : "/";

    public static Dictionary<string, object?> ToProxy(ApiResponse resp) => new()
    {
        ["statusCode"] = (long)resp.Status,
        ["headers"] = new Dictionary<string, string>(resp.Headers),
        ["isBase64Encoded"] = false,
        ["body"] = resp.Text(),
    };

    public static async Task<Stream> HandleAsync(ApiRouter api, Stream input)
    {
        var text = await new StreamReader(input, Encoding.UTF8).ReadToEndAsync();
        var resp = await api.HandleAsync(ToRequest((IReadOnlyDictionary<string, object?>)Json.Parse(text)!));
        return new MemoryStream(Encoding.UTF8.GetBytes(Json.Write(ToProxy(resp))));
    }
}
'''

ASPNET = r'''using Microsoft.AspNetCore.Builder;
using Microsoft.AspNetCore.Http;
using Microsoft.AspNetCore.Routing;

namespace __NS__;

/// <summary>
/// Adattatore ASP.NET Core (minimal API), per i microservizi su Kubernetes dietro il gateway: ogni percorso del contratto
/// diventa un endpoint; validazione, errori e identità restano del nucleo. app.MapKybesApi(api);
/// </summary>
public static class AspNetAdapter
{
    public static async Task<ApiRequest> ToRequestAsync(HttpRequest request)
    {
        var headers = new Dictionary<string, string>();
        foreach (var h in request.Headers) headers[h.Key.ToLowerInvariant()] = string.Join(", ", h.Value.ToArray());
        var buffer = new MemoryStream();
        await request.Body.CopyToAsync(buffer);
        var body = buffer.ToArray();
        return new ApiRequest(request.Method, request.PathBase.Add(request.Path).ToUriComponent(), ApiRequest.ParseQuery(request.QueryString.Value),
            headers, body.Length > 0 ? body : null, IdentityReader.FromHeaders(headers));
    }

    public static async Task WriteAsync(HttpResponse response, ApiResponse resp)
    {
        response.StatusCode = resp.Status;
        foreach (var h in resp.Headers) response.Headers[h.Key] = h.Value;
        var text = resp.Text();
        if (text.Length > 0) await response.WriteAsync(text);
    }

    /// <summary>Un endpoint per ogni percorso delle operazioni dell'ApiRouter (qualsiasi metodo: il 405 lo decide il nucleo).</summary>
    public static IEndpointRouteBuilder MapKybesApi(this IEndpointRouteBuilder app, ApiRouter api)
    {
        foreach (var path in api.Routes.Select(r => api.BasePath + r.Spec.Path).Distinct())
        {
            app.Map(path, async context => await WriteAsync(context.Response, await api.HandleAsync(await ToRequestAsync(context.Request))));
        }
        return app;
    }
}
'''

FILES = {"Json.cs": JSON, "JsonSchema.cs": SCHEMA, "Http.cs": HTTP, "IdentityReader.cs": IDENTITY, "Router.cs": ROUTER,
         "ApiData.cs": DATA, "ApiConvert.cs": CONVERT, "LambdaAdapter.cs": LAMBDA, "AspNetAdapter.cs": ASPNET}


def cstr(s: str) -> str:
    """Letterale stringa C# (regolare, con escape)."""
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


def files(ns: str, model_ns: str, sql: bool, mongo: bool, claims: Dict, headers: Dict) -> Dict[str, str]:
    out = {}
    for name, text in FILES.items():
        t = USINGS + text.lstrip("\n") if not text.startswith("using") else USINGS + text
        t = t.replace("__NS__", ns).replace("__MODEL__", model_ns)
        t = (t.replace("__CLAIM_SUBJECT__", cstr(claims["subject"])).replace("__CLAIM_TENANT__", cstr(claims["tenant"]))
             .replace("__CLAIM_SCOPES__", ", ".join(cstr(s) for s in claims["scopes"]))
             .replace("__HEADER_SUBJECT__", cstr(headers["subject"])).replace("__HEADER_TENANT__", cstr(headers["tenant"]))
             .replace("__HEADER_SCOPES__", cstr(headers["scopes"])))
        out[name] = _strip_block(strip_sql(t, sql), "mongo", mongo)
    return out
