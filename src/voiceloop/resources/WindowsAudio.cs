// Windows audio policy service interop. No registry ownership or ACL changes.
using System;
using System.Runtime.InteropServices;

namespace VoiceLoop {
    [StructLayout(LayoutKind.Sequential)]
    public struct PropertyKey { public Guid Format; public uint Id;
        public PropertyKey(string format, uint id) { Format = new Guid(format); Id = id; } }
    [StructLayout(LayoutKind.Explicit, Size = 24)]
    public struct PropVariant {
        [FieldOffset(0)] public ushort Type;
        [FieldOffset(8)] public IntPtr Pointer;
    }
    [ComImport, Guid("870af99c-171d-4f9e-af0d-e63df40c2bc9")]
    internal class PolicyClient { }
    [ComImport, Guid("bcde0395-e52f-467c-8e3d-c4579291692e")]
    internal class DeviceEnumerator { }
    [ComImport, Guid("a95664d2-9614-4f35-a746-de8db63617e6"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    internal interface IMMDeviceEnumerator {
        void EnumAudioEndpoints(int flow, int mask, out IntPtr devices);
        void GetDefaultAudioEndpoint(int flow, int role, out IMMDevice device);
    }
    [ComImport, Guid("d666063f-1587-4e43-81f1-b948e807363f"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    internal interface IMMDevice {
        void Activate(ref Guid iid, int context, IntPtr parameters, out IntPtr obj);
        void OpenPropertyStore(int access, out IntPtr store);
        void GetId([MarshalAs(UnmanagedType.LPWStr)] out string id);
    }
    [ComImport, Guid("f8679f50-850a-41cf-9c72-430f290290c8"), InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    internal interface IPolicyConfig {
        void GetMixFormat([MarshalAs(UnmanagedType.LPWStr)] string id, out IntPtr format);
        void GetDeviceFormat([MarshalAs(UnmanagedType.LPWStr)] string id, int defaultFormat, out IntPtr format);
        void ResetDeviceFormat([MarshalAs(UnmanagedType.LPWStr)] string id);
        void SetDeviceFormat([MarshalAs(UnmanagedType.LPWStr)] string id, IntPtr endpoint, IntPtr mix);
        void GetProcessingPeriod([MarshalAs(UnmanagedType.LPWStr)] string id, int defaultPeriod, IntPtr period, IntPtr minimum);
        void SetProcessingPeriod([MarshalAs(UnmanagedType.LPWStr)] string id, IntPtr period);
        void GetShareMode([MarshalAs(UnmanagedType.LPWStr)] string id, IntPtr mode);
        void SetShareMode([MarshalAs(UnmanagedType.LPWStr)] string id, IntPtr mode);
        void GetPropertyValue([MarshalAs(UnmanagedType.LPWStr)] string id, int fxStore, ref PropertyKey key, out PropVariant value);
        void SetPropertyValue([MarshalAs(UnmanagedType.LPWStr)] string id, int fxStore, ref PropertyKey key, ref PropVariant value);
        void SetDefaultEndpoint([MarshalAs(UnmanagedType.LPWStr)] string id, int role);
        void SetEndpointVisibility([MarshalAs(UnmanagedType.LPWStr)] string id, int visible);
    }
    public static class AudioNames {
        [DllImport("cfgmgr32.dll", CharSet = CharSet.Unicode)]
        private static extern uint CM_Locate_DevNodeW(out uint node, string id, uint flags);
        [DllImport("cfgmgr32.dll", CharSet = CharSet.Unicode)]
        private static extern uint CM_Set_DevNode_PropertyW(uint node, ref PropertyKey key, uint type,
            IntPtr buffer, uint length, uint flags);
        [DllImport("ole32.dll")] private static extern int PropVariantClear(ref PropVariant value);
        public static string Rename(string id, string name) {
            var policy = (IPolicyConfig)new PolicyClient();
            var key = new PropertyKey("a45c254e-df1c-4efd-8020-67d146a850e0", 14);
            var value = new PropVariant { Type = 31, Pointer = Marshal.StringToCoTaskMemUni(name) };
            try {
                // The friendly name (PID 14) is computed and read-only in WASAPI.
                // Set the user-editable endpoint description, as Windows Sound settings does.
                var description = new PropertyKey("a45c254e-df1c-4efd-8020-67d146a850e0", 2);
                policy.SetPropertyValue(id, 0, ref description, ref value);
                uint node;
                uint result = CM_Locate_DevNodeW(out node, "SWD\\MMDEVAPI\\" + id, 0);
                if (result != 0) throw new InvalidOperationException("Locate audio endpoint: " + result);
                result = CM_Set_DevNode_PropertyW(node, ref key, 0x12, value.Pointer,
                    (uint)((name.Length + 1) * 2), 0);
                if (result != 0) throw new InvalidOperationException("Rename audio endpoint: " + result);
                PropVariant actual;
                policy.GetPropertyValue(id, 0, ref description, out actual);
                try { return actual.Type == 31 ? Marshal.PtrToStringUni(actual.Pointer) : ""; }
                finally { PropVariantClear(ref actual); }
            } finally { PropVariantClear(ref value); Marshal.ReleaseComObject(policy); }
        }
        public static string DefaultDevice(int flow, int role) {
            var enumerator = (IMMDeviceEnumerator)new DeviceEnumerator();
            try {
                IMMDevice device;
                enumerator.GetDefaultAudioEndpoint(flow, role, out device);
                try { string id; device.GetId(out id); return id; }
                finally { Marshal.ReleaseComObject(device); }
            } catch (COMException) { return ""; }
            finally { Marshal.ReleaseComObject(enumerator); }
        }
        public static void RestoreDefault(string id, int role) {
            if (String.IsNullOrEmpty(id)) return;
            var policy = (IPolicyConfig)new PolicyClient();
            try { policy.SetDefaultEndpoint(id, role); }
            finally { Marshal.ReleaseComObject(policy); }
        }
        public static void SetRate(string id, int rate) {
            var policy = (IPolicyConfig)new PolicyClient();
            IntPtr format = IntPtr.Zero;
            try {
                policy.GetDeviceFormat(id, 0, out format);
                int align = (ushort)Marshal.ReadInt16(format, 12);
                if (align == 0 || align > 128) throw new InvalidOperationException("Invalid audio format.");
                Marshal.WriteInt32(format, 4, rate);
                Marshal.WriteInt32(format, 8, rate * align);
                policy.SetDeviceFormat(id, format, IntPtr.Zero);
            } finally {
                if (format != IntPtr.Zero) Marshal.FreeCoTaskMem(format);
                Marshal.ReleaseComObject(policy);
            }
        }
    }
}
