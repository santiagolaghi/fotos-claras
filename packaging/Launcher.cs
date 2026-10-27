using System;
using System.Diagnostics;
using System.IO;
using System.Text;
using System.Text.RegularExpressions;
using System.Windows.Forms;

// Small native Windows entry point. App data and photographs are outside this tree.
internal static class Launcher {
    static readonly string Root=AppDomain.CurrentDomain.BaseDirectory;
    static string Read(string name) {
        string path=Path.Combine(Root,name);
        if (!File.Exists(path)) return "";
        string value=File.ReadAllText(path).Trim();
        return Regex.IsMatch(value,@"^\d+\.\d+\.\d+(?:-beta\.\d+)?$") ? value : "";
    }
    static string Exe(string version) {
        return Path.Combine(Root,"versions",version,"FotosClaras.exe");
    }
    static void ReplacePointer(string name,string value) {
        string path=Path.Combine(Root,name),temp=path+".new";
        File.WriteAllText(temp,value,new UTF8Encoding(false));
        if (File.Exists(path)) File.Replace(temp,path,null); else File.Move(temp,path);
    }
    [STAThread]
    static int Main(string[] args) {
        bool smoke=Array.IndexOf(args,"--smoke")>=0;
        bool rollbackSmoke=Array.IndexOf(args,"--rollback-smoke")>=0;
        bool rollback=rollbackSmoke || Array.IndexOf(args,"--rollback")>=0;
        try {
            string active=Read("active-version.txt"), previous=Read("previous-version.txt");
            if (rollback) {
                if (previous=="" || !File.Exists(Exe(previous))) throw new IOException("No hay una version anterior disponible.");
                if (!rollbackSmoke && MessageBox.Show("Cerra Fotos Claras antes de continuar. Volver a la version anterior?","Fotos Claras",MessageBoxButtons.YesNo,MessageBoxIcon.Question)!=DialogResult.Yes) return 0;
                ReplacePointer("active-version.txt",previous);
                if (active!="") ReplacePointer("previous-version.txt",active);
                active=previous;
            }
            if (active=="" || !File.Exists(Exe(active))) active=previous;
            if (active=="" || !File.Exists(Exe(active))) throw new IOException("No se encontro una version completa. Volve a ejecutar el instalador.");
            var info=new ProcessStartInfo(Exe(active),(smoke || rollbackSmoke) ? "--smoke" : "");
            info.WorkingDirectory=Path.GetDirectoryName(Exe(active));
            info.UseShellExecute=false;
            using (Process app=Process.Start(info)) {
                if (smoke || rollbackSmoke) {
                    if (!app.WaitForExit(60000)) { app.Kill(); return 2; }
                    return app.ExitCode;
                }
            }
            return 0;
        } catch (Exception error) {
            if (!(smoke || rollbackSmoke)) MessageBox.Show(error.Message,"Fotos Claras",MessageBoxButtons.OK,MessageBoxIcon.Error);
            return 1;
        }
    }
}
