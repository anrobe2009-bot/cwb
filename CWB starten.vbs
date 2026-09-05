' FILE: CWB starten.vbs
Option Explicit

Dim fso, shell, basis, skript, pyw, befehl
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

basis = fso.GetParentFolderName(WScript.ScriptFullName)
skript = fso.BuildPath(basis, "core\fenster.py")

If Not fso.FileExists(skript) Then
    MsgBox "Nicht gefunden: " & skript, vbCritical, "CWB"
    WScript.Quit 1
End If

pyw = PythonwFinden()

befehl = """" & pyw & """ """ & skript & """"
shell.CurrentDirectory = basis
shell.Run befehl, 0, False


Function PythonwFinden()
    Dim pfad
    pfad = AusRegistry()
    If pfad = "" Then pfad = AusPfad()
    If pfad = "" Then pfad = "pythonw"
    PythonwFinden = pfad
End Function


Function AusRegistry()
    Dim wurzeln, versionen, w, v, basisSchluessel, installPfad, kandidat
    AusRegistry = ""

    wurzeln = Array("HKCU\Software\Python\PythonCore\", _
                    "HKLM\Software\Python\PythonCore\", _
                    "HKLM\Software\Wow6432Node\Python\PythonCore\")

    versionen = Array("3.13", "3.12", "3.11", "3.10", "3.9", "3.8", _
                      "3.13-32", "3.12-32", "3.11-32", "3.10-32")

    For Each w In wurzeln
        For Each v In versionen
            basisSchluessel = w & v & "\InstallPath\"
            installPfad = SchluesselLesen(basisSchluessel & "ExecutablePath")
            If installPfad <> "" Then
                kandidat = Replace(installPfad, "python.exe", "pythonw.exe")
                If fso.FileExists(kandidat) Then
                    AusRegistry = kandidat
                    Exit Function
                End If
            End If

            installPfad = SchluesselLesen(basisSchluessel)
            If installPfad <> "" Then
                kandidat = fso.BuildPath(installPfad, "pythonw.exe")
                If fso.FileExists(kandidat) Then
                    AusRegistry = kandidat
                    Exit Function
                End If
            End If
        Next
    Next
End Function


Function SchluesselLesen(schluessel)
    SchluesselLesen = ""
    On Error Resume Next
    SchluesselLesen = shell.RegRead(schluessel)
    If Err.Number <> 0 Then
        SchluesselLesen = ""
        Err.Clear
    End If
    On Error GoTo 0
End Function


Function AusPfad()
    Dim teile, t, ordner, kandidat
    AusPfad = ""
    teile = Split(shell.ExpandEnvironmentStrings("%PATH%"), ";")
    For Each t In teile
        ordner = Trim(t)
        If ordner <> "" Then
            kandidat = fso.BuildPath(ordner, "pythonw.exe")
            On Error Resume Next
            If fso.FileExists(kandidat) Then
                AusPfad = kandidat
                Err.Clear
                On Error GoTo 0
                Exit Function
            End If
            Err.Clear
            On Error GoTo 0
        End If
    Next
End Function
