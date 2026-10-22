using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Net;
using System.Net.Sockets;
using System.Text;
using System.Threading;
using BepInEx;
using BepInEx.Logging;
using Newtonsoft.Json;
using Newtonsoft.Json.Linq;

namespace HSbgAgent
{
    /// <summary>
    /// Managed action-injection bridge for HSbg. Runs inside Hearthstone (BepInEx),
    /// so it can call the client's own Network.SendOption / SendChoices without UI
    /// clicks and without touching the encrypted transport.
    ///
    /// Protocol: one JSON object per line over TCP 127.0.0.1:17890.
    ///   {"cmd":"ping"}
    ///   {"cmd":"state"}
    ///   {"cmd":"option","id":...,"main":...,"target":...,"sub":...,"pos":...}
    ///   {"cmd":"choices","id":...,"picks":[...]}
    ///   {"cmd":"select","entity":...}      // choose a single entity if choices active
    /// </summary>
    [BepInPlugin("hsbg.agent", "HSbg Action Bridge", "0.1.0")]
    public class AgentPlugin : BaseUnityPlugin
    {
        private const int Port = 17890;
        private static ManualLogSource Log;
        private TcpListener _listener;
        private Thread _serverThread;
        private volatile bool _running;
        private readonly ConcurrentQueue<Action> _mainQueue = new ConcurrentQueue<Action>();

        private void Awake()
        {
            Log = Logger;
            Log.LogInfo("[HSbgAgent] plugin loaded; starting bridge on 127.0.0.1:" + Port);
            _running = true;
            _serverThread = new Thread(ServerLoop) { IsBackground = true, Name = "HSbgAgentBridge" };
            _serverThread.Start();
        }

        private void Update()
        {
            // All Unity/GameState calls must run on the main thread.
            while (_mainQueue.TryDequeue(out var action))
            {
                try { action(); }
                catch (Exception e) { Log?.LogError("[HSbgAgent] main queue: " + e); }
            }
        }

        private void OnDestroy()
        {
            _running = false;
            try { _listener?.Stop(); } catch { }
        }

        private void ServerLoop()
        {
            try
            {
                _listener = new TcpListener(IPAddress.Loopback, Port);
                _listener.Start();
                Log.LogInfo("[HSbgAgent] listening");
                while (_running)
                {
                    TcpClient client;
                    try { client = _listener.AcceptTcpClient(); }
                    catch { break; }
                    var t = new Thread(() => HandleClient(client)) { IsBackground = true };
                    t.Start();
                }
            }
            catch (Exception e)
            {
                Log?.LogError("[HSbgAgent] listener: " + e);
            }
        }

        private void HandleClient(TcpClient client)
        {
            using (client)
            using (var stream = client.GetStream())
            using (var reader = new StreamReader(stream, new UTF8Encoding(false)))
            using (var writer = new StreamWriter(stream, new UTF8Encoding(false)) { AutoFlush = true })
            {
                string line;
                while (_running && (line = reader.ReadLine()) != null)
                {
                    object response;
                    try { response = HandleLine(line); }
                    catch (Exception e)
                    {
                        response = new { ok = false, error = e.GetType().Name + ": " + e.Message };
                        Log?.LogError("[HSbgAgent] " + e);
                    }
                    try { writer.WriteLine(JsonConvert.SerializeObject(response)); }
                    catch { break; }
                }
            }
        }

        private object InvokeOnMainThread(Func<object> fn, int timeoutMs)
        {
            object result = null;
            Exception error = null;
            var done = new ManualResetEventSlim(false);
            _mainQueue.Enqueue(() =>
            {
                try { result = fn(); }
                catch (Exception e) { error = e; }
                finally { done.Set(); }
            });
            if (!done.Wait(timeoutMs))
                return new { ok = false, error = "main-thread timeout" };
            if (error != null)
                return new { ok = false, error = error.GetType().Name + ": " + error.Message };
            return result;
        }

        private object HandleLine(string line)
        {
            var req = JsonConvert.DeserializeObject<Dictionary<string, object>>(line);
            if (req == null || !req.TryGetValue("cmd", out var cmdObj))
                return new { ok = false, error = "missing cmd" };
            string cmd = Convert.ToString(cmdObj);
            switch (cmd)
            {
                case "ping":
                    return new { ok = true, pong = true, time = DateTime.Now.ToString("O") };
                case "state":
                    return InvokeOnMainThread(State, 5000);
                case "option":
                    int id = GetInt(req, "id");
                    int main = GetInt(req, "main");
                    int target = GetInt(req, "target");
                    int sub = GetInt(req, "sub", -1);
                    int pos = GetInt(req, "pos");
                    return InvokeOnMainThread(() =>
                    {
                        Network.Get().SendOption(id, main, target, sub, pos);
                        Log.LogInfo($"[HSbgAgent] SendOption id={id} main={main} target={target} sub={sub} pos={pos}");
                        return new { ok = true, sent = "option", id, main, target, sub, pos };
                    }, 5000);
                case "choices":
                    int cid = GetInt(req, "id");
                    var picks = GetIntList(req, "picks");
                    return InvokeOnMainThread(() =>
                    {
                        Network.Get().SendChoices(cid, picks);
                        Log.LogInfo($"[HSbgAgent] SendChoices id={cid} picks={string.Join(",", picks)}");
                        return new { ok = true, sent = "choices", id = cid, picks };
                    }, 5000);
                case "select":
                    int entity = GetInt(req, "entity");
                    return InvokeOnMainThread(() =>
                    {
                        var choices = GameState.Get()?.GetFriendlyEntityChoices();
                        if (choices == null) return new { ok = false, error = "no friendly choices" };
                        Network.Get().SendChoices(choices.ID, new List<int> { entity });
                        Log.LogInfo($"[HSbgAgent] SendChoices(single) id={choices.ID} entity={entity}");
                        return new { ok = true, sent = "choices", id = choices.ID, picks = new[] { entity } };
                    }, 5000);
                case "concede":
                    return InvokeOnMainThread(() =>
                    {
                        Network.Get().Concede();
                        return new { ok = true, sent = "concede" };
                    }, 5000);
                default:
                    return new { ok = false, error = "unknown cmd: " + cmd };
            }
        }

        private object State()
        {
            var gs = GameState.Get();
            if (gs == null) return new { ok = false, error = "no GameState" };
            var options = gs.GetOptionsPacket();
            var choices = gs.GetFriendlyEntityChoices();
            var optList = new List<object>();
            if (options != null)
            {
                foreach (var opt in options.List)
                {
                    var targets = new List<int>();
                    if (opt.Main?.Targets != null)
                        foreach (var t in opt.Main.Targets) targets.Add(t.ID);
                    var subs = new List<object>();
                    if (opt.Subs != null)
                        foreach (var s in opt.Subs)
                        {
                            var st = new List<int>();
                            if (s.Targets != null)
                                foreach (var t in s.Targets) st.Add(t.ID);
                            subs.Add(new { id = s.ID, targets = st, keyword = s.PowerKeyword.ToString() });
                        }
                    optList.Add(new
                    {
                        type = opt.Type.ToString(),
                        main = opt.Main?.ID ?? 0,
                        targets,
                        subs,
                    });
                }
            }
            object choice = null;
            if (choices != null)
            {
                choice = new
                {
                    id = choices.ID,
                    type = choices.ChoiceType.ToString(),
                    entities = choices.Entities,
                    unchoosable = choices.UnchoosableEntities,
                    count_min = choices.CountMin,
                    count_max = choices.CountMax,
                    source = choices.Source,
                };
            }
            return new
            {
                ok = true,
                options_id = options?.ID ?? 0,
                options = optList,
                choice,
                friendly_player = gs.GetFriendlyPlayerId(),
            };
        }

        private static int GetInt(Dictionary<string, object> d, string key, int def = 0)
        {
            if (!d.TryGetValue(key, out var v) || v == null) return def;
            try { return Convert.ToInt32(v); } catch { return def; }
        }

        private static List<int> GetIntList(Dictionary<string, object> d, string key)
        {
            var result = new List<int>();
            if (!d.TryGetValue(key, out var v) || v == null) return result;
            if (v is JArray arr) return arr.Select(x => Convert.ToInt32(x)).ToList();
            if (v is IEnumerable<object> objs) return objs.Select(x => Convert.ToInt32(x)).ToList();
            result.Add(Convert.ToInt32(v));
            return result;
        }
    }
}
