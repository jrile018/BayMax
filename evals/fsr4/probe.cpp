// Signed AMD FSR SDK 2.3 DX12 diagnostic; context identity is not ML proof.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <d3d12.h>
#include <dxgi1_6.h>
#include <ffx_api.h>
#include <dx12/ffx_api_dx12.h>
#include <ffx_upscale.h>
#include "probe-helpers.h"
#include <algorithm>
#include <cmath>
#include <cstring>
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>
#include <vector>
#include <stdexcept>
#include <limits>
namespace {
static_assert(FFX_UPSCALER_VERSION_MAJOR==4 && FFX_UPSCALER_VERSION_MINOR==1 &&
              FFX_UPSCALER_VERSION_PATCH==1,"SDK 2.3 FSR 4.1.1 headers required");
constexpr UINT rw=64,rh=64,ow=96,oh=96;
constexpr uint64_t budget=UINT64_C(1)<<30;
const char *currentStage="arguments";
template<class T> class Com {
    T *value=nullptr;
public:
    ~Com() { if (value) value->Release(); }
    Com()=default; Com(const Com &)=delete; Com &operator=(const Com &)=delete;
    T *get() const { return value; }
    T *operator->() const { return value; }
    T **put() { if (value) value->Release(); value=nullptr; return &value; }
};
struct Handle { HANDLE value=nullptr; ~Handle() { if (value) CloseHandle(value); } };
static std::string hex64(uint64_t v) {
    std::ostringstream s; s<<std::hex<<std::setw(16)<<std::setfill('0')<<v; return s.str();
}
static std::string narrow(const wchar_t *s) {
    if (!s) return {};
    const int n=WideCharToMultiByte(CP_UTF8,0,s,-1,nullptr,0,nullptr,nullptr);
    if (!n) throw std::runtime_error("WideCharToMultiByte failed");
    std::vector<char> b(static_cast<size_t>(n));
    if (!WideCharToMultiByte(CP_UTF8,0,s,-1,b.data(),n,nullptr,nullptr)) throw std::runtime_error("wide string conversion failed");
    return b.data();
}
static void event(const std::string &fields) {
    static SRWLOCK lock=SRWLOCK_INIT;
    AcquireSRWLockExclusive(&lock);
    std::cout<<"{"<<fields<<"}\n"; std::cout.flush();
    ReleaseSRWLockExclusive(&lock);
}
static void stage(const char *name) {
    currentStage=name; event("\"event\":\"stage\",\"stage\":"+probe::json_quote(name));
}
static HRESULT hr(const char *name,HRESULT code,bool fatal=true) {
    event("\"event\":\"api\",\"api\":"+probe::json_quote(name)+",\"hresult\":"+probe::json_quote(hex64(static_cast<uint32_t>(code))));
    if (FAILED(code) && fatal) throw std::runtime_error(std::string(name)+" failed");
    return code;
}
static void message(uint32_t type,const wchar_t *text) {
    try { event("\"event\":\"sdk_message\",\"type\":"+std::to_string(type)+",\"message_utf8_bytes\":"+probe::json_quote(narrow(text))); }
    catch (...) { event("\"event\":\"sdk_message_encoding_error\""); }
}
struct Options { bool dispatch=false,luidSet=false,deviceIdSet=false; unsigned frames=3; uint64_t luid=0; uint32_t deviceId=0; std::wstring dllDir; };
static Options options(int argc,wchar_t **argv) {
    Options o; bool mode=false;
    for (int i=1;i<argc;++i) {
        const std::wstring a=argv[i];
        if (a==L"--query-only" || a==L"--dispatch") {
            if (mode) throw std::runtime_error("specify one mode");
            mode=true; o.dispatch=a==L"--dispatch";
        } else if (a==L"--frames" && i+1<argc) o.frames=probe::parse_frames(narrow(argv[++i]));
        else if (a==L"--dll-dir" && i+1<argc) o.dllDir=argv[++i];
        else if (a==L"--adapter-luid" && i+1<argc) {
            const auto s=narrow(argv[++i]); size_t used=0;
            if (s.empty() || s.size()>16 || s.find_first_not_of("0123456789abcdefABCDEF")!=std::string::npos)
                throw std::runtime_error("--adapter-luid needs 1..16 hex digits");
            o.luid=std::stoull(s,&used,16); o.luidSet=true;
        } else if (a==L"--adapter-device-id" && i+1<argc) {
            const auto s=narrow(argv[++i]); size_t used=0;
            if (s.empty() || s.size()>8 || s.find_first_not_of("0123456789abcdefABCDEF")!=std::string::npos)
                throw std::runtime_error("--adapter-device-id needs 1..8 hex digits");
            o.deviceId=static_cast<uint32_t>(std::stoul(s,&used,16)); o.deviceIdSet=true;
        } else throw std::runtime_error("unknown/incomplete argument");
    }
    if (!mode || o.dllDir.empty() || !o.deviceIdSet)
        throw std::runtime_error("required: --query-only|--dispatch --dll-dir ABS_WINDOWS_PATH --adapter-device-id HEX");
    if (o.dllDir.size()<3 || o.dllDir[1]!=L':' || (o.dllDir[2]!=L'\\' && o.dllDir[2]!=L'/'))
        throw std::runtime_error("--dll-dir must be an absolute drive path");
    return o;
}
struct Api {
    HMODULE module=nullptr;
    std::wstring directory;
    PfnFfxCreateContext create=nullptr; PfnFfxDestroyContext destroy=nullptr;
    PfnFfxQuery query=nullptr; PfnFfxDispatch dispatch=nullptr; PfnFfxConfigure configure=nullptr;
    ~Api() { if (module) FreeLibrary(module); }
    template<class T> T symbol(const char *name) {
        const FARPROC p=GetProcAddress(module,name);
        event("\"event\":\"symbol\",\"name\":"+probe::json_quote(name)+",\"found\":"+(p?"true":"false"));
        if (!p) throw std::runtime_error(std::string("missing SDK entrypoint ")+name);
        static_assert(sizeof(T)==sizeof(p),"Win64 function pointer size");
        T typed; std::memcpy(&typed,&p,sizeof(typed)); return typed;
    }
    void load(const Options &o) {
        directory=o.dllDir;
        if (!SetDllDirectoryW(o.dllDir.c_str())) throw std::runtime_error("SetDllDirectoryW failed");
        const auto path=o.dllDir+L"\\amd_fidelityfx_loader_dx12.dll";
        module=LoadLibraryW(path.c_str());
        const DWORD loadError=module?0:GetLastError();
        event("\"event\":\"loader\",\"path_utf8_bytes\":"+probe::json_quote(narrow(path.c_str()))+
              ",\"loaded\":"+(module?"true":"false")+",\"win32_error\":"+std::to_string(loadError));
        if (!module) throw std::runtime_error("LoadLibraryW failed");
        create=symbol<PfnFfxCreateContext>("ffxCreateContext"); destroy=symbol<PfnFfxDestroyContext>("ffxDestroyContext");
        query=symbol<PfnFfxQuery>("ffxQuery"); dispatch=symbol<PfnFfxDispatch>("ffxDispatch");
        configure=symbol<PfnFfxConfigure>("ffxConfigure");
        verifyModule(L"amd_fidelityfx_loader_dx12.dll");
    }
    static std::wstring fullPath(const std::wstring &value) {
        std::vector<wchar_t> path(32768);
        const DWORD count=GetFullPathNameW(value.c_str(),static_cast<DWORD>(path.size()),path.data(),nullptr);
        if (!count || count>=path.size()) throw std::runtime_error("cannot normalize SDK module path");
        std::wstring result(path.data(),count);
        std::replace(result.begin(),result.end(),L'/',L'\\');
        return result;
    }
    void verifyModule(const wchar_t *name) {
        const HMODULE loaded=GetModuleHandleW(name);
        std::vector<wchar_t> path(32768);
        const DWORD count=loaded?GetModuleFileNameW(loaded,path.data(),static_cast<DWORD>(path.size())):0;
        event("\"event\":\"loaded_module\",\"name_utf8_bytes\":"+probe::json_quote(narrow(name))+
              ",\"loaded\":"+(loaded?"true":"false")+",\"path_utf8_bytes\":"+
              probe::json_quote(count && count<path.size()?narrow(path.data()):""));
        if (!loaded || !count || count>=path.size()) throw std::runtime_error("required signed SDK module missing/path unavailable");
        const auto actual=fullPath(path.data()),expected=fullPath(directory+L"\\"+name);
        const bool matches=CompareStringOrdinal(actual.c_str(),-1,expected.c_str(),-1,TRUE)==CSTR_EQUAL;
        event("\"event\":\"module_path_verification\",\"name_utf8_bytes\":"+probe::json_quote(narrow(name))+
              ",\"expected_path_utf8_bytes\":"+probe::json_quote(narrow(expected.c_str()))+
              ",\"matches_expected\":"+(matches?"true":"false"));
        if (!matches) throw std::runtime_error("SDK module loaded outside requested signed DLL directory");
    }
    void reportModules() {
        stage("signed_module_path_verification");
        verifyModule(L"amd_fidelityfx_loader_dx12.dll");
        verifyModule(L"amd_fidelityfx_upscaler_dx12.dll");
    }
    ffxReturnCode_t rc(const char *name,ffxReturnCode_t code,bool fatal=true) {
        event("\"event\":\"api\",\"api\":"+probe::json_quote(name)+",\"ffx_code\":"+std::to_string(code));
        if (fatal && code!=FFX_API_RETURN_OK) throw std::runtime_error(std::string(name)+" failed");
        return code;
    }
};
static uint64_t packLuid(const LUID &l) {
    return (static_cast<uint64_t>(static_cast<uint32_t>(l.HighPart))<<32)|l.LowPart;
}
static void device(const Options &o,Com<ID3D12Device> &out) {
    Com<IDXGIFactory4> factory; hr("CreateDXGIFactory1",CreateDXGIFactory1(IID_PPV_ARGS(factory.put())));
    Com<IDXGIAdapter1> chosen; unsigned matches=0;
    for (UINT index=0;index<64;++index) {
        Com<IDXGIAdapter1> adapter;
        const auto code=hr("EnumAdapters1",factory->EnumAdapters1(index,adapter.put()),false);
        if (code==DXGI_ERROR_NOT_FOUND) break;
        if (FAILED(code)) throw std::runtime_error("adapter enumeration failed");
        DXGI_ADAPTER_DESC1 d{}; hr("GetDesc1",adapter->GetDesc1(&d)); const auto luid=packLuid(d.AdapterLuid);
        event("\"event\":\"adapter\",\"name_utf8_bytes\":"+probe::json_quote(narrow(d.Description))+
              ",\"luid\":"+probe::json_quote(hex64(luid))+",\"vendor_id\":"+std::to_string(d.VendorId)+
              ",\"device_id\":"+std::to_string(d.DeviceId)+",\"dedicated_video_memory\":"+std::to_string(d.DedicatedVideoMemory)+
              ",\"software\":"+((d.Flags&DXGI_ADAPTER_FLAG_SOFTWARE)?"true":"false"));
        if (d.VendorId!=0x1002 || d.DeviceId!=o.deviceId ||
            (d.Flags&DXGI_ADAPTER_FLAG_SOFTWARE) || (o.luidSet && luid!=o.luid)) continue;
        ++matches; hr("AMD adapter QueryInterface",adapter->QueryInterface(IID_PPV_ARGS(chosen.put())));
    }
    if (matches!=1) throw std::runtime_error("need one matching AMD adapter; use --adapter-luid");
    DXGI_ADAPTER_DESC1 selected{};
    hr("selected AMD GetDesc1",chosen->GetDesc1(&selected));
    event("\"event\":\"selected_adapter\",\"name_utf8_bytes\":"+probe::json_quote(narrow(selected.Description))+
          ",\"luid\":"+probe::json_quote(hex64(packLuid(selected.AdapterLuid))));
    hr("D3D12CreateDevice",D3D12CreateDevice(chosen.get(),D3D_FEATURE_LEVEL_12_0,IID_PPV_ARGS(out.put())));
    D3D12_FEATURE_DATA_D3D12_OPTIONS caps{};
    const auto capCode=hr("CheckFeatureSupport OPTIONS",out->CheckFeatureSupport(D3D12_FEATURE_D3D12_OPTIONS,&caps,sizeof(caps)),false);
    D3D12_FEATURE_DATA_SHADER_MODEL sm{D3D_SHADER_MODEL_6_6};
    const auto smCode=hr("CheckFeatureSupport SHADER_MODEL",out->CheckFeatureSupport(D3D12_FEATURE_SHADER_MODEL,&sm,sizeof(sm)),false);
    event("\"event\":\"dx12_features\",\"feature_level_requested\":\"12_0\",\"options_available\":"+
          std::string(SUCCEEDED(capCode)?"true":"false")+",\"resource_binding_tier\":"+std::to_string(caps.ResourceBindingTier)+
          ",\"shader_model_query_available\":"+(SUCCEEDED(smCode)?"true":"false")+
          ",\"highest_shader_model_up_to_6_6\":"+std::to_string(sm.HighestShaderModel));
    D3D12_FEATURE_DATA_D3D12_OPTIONS1 wave{};
    const auto waveCode=hr("CheckFeatureSupport OPTIONS1",out->CheckFeatureSupport(D3D12_FEATURE_D3D12_OPTIONS1,&wave,sizeof(wave)),false);
    event("\"event\":\"wave_features\",\"available\":"+std::string(SUCCEEDED(waveCode)?"true":"false")+
          ",\"wave_ops\":"+(wave.WaveOps?"true":"false")+",\"wave_lane_min\":"+std::to_string(wave.WaveLaneCountMin)+
          ",\"wave_lane_max\":"+std::to_string(wave.WaveLaneCountMax));
}
struct Context {
    Api &api; ffxContext value=nullptr;
    ffxCreateContextDescUpscale desc{}; ffxCreateBackendDX12Desc backend{};
    ffxOverrideVersion overrideDesc{}; ffxCreateContextDescUpscaleVersion version{};
    uint64_t selectedId=0; std::string selectedName;
    explicit Context(Api &a):api(a) {}
    ~Context() { if (value) api.rc("ffxDestroyContext cleanup",api.destroy(&value,nullptr),false); }
    void enumerate(ID3D12Device *dev) {
        stage("provider_enumeration"); uint64_t count=0;
        ffxQueryDescGetVersions q{}; q.header.type=FFX_API_QUERY_DESC_TYPE_GET_VERSIONS;
        q.createDescType=FFX_API_CREATE_CONTEXT_DESC_TYPE_UPSCALE; q.device=dev; q.outputCount=&count;
        api.rc("ffxQuery GetVersions count",api.query(nullptr,&q.header));
        if (!count || count>256) throw std::runtime_error("invalid/bounded provider count");
        const auto capacity=count;
        std::vector<uint64_t> ids(static_cast<size_t>(count));
        std::vector<const char *> names(static_cast<size_t>(count));
        q.versionIds=ids.data(); q.versionNames=names.data();
        api.rc("ffxQuery GetVersions list",api.query(nullptr,&q.header));
        if (count>capacity) throw std::runtime_error("provider count grew beyond capacity");
        // Copy before later queries can overwrite SDK-global provider name storage.
        std::vector<std::string> copies;
        for (uint64_t i=0;i<count;++i) copies.emplace_back(names[i]?names[i]:"");
        unsigned targets=0;
        for (uint64_t i=0;i<count;++i) {
            event("\"event\":\"provider\",\"id\":"+probe::json_quote(hex64(ids[i]))+",\"name_bytes\":"+probe::json_quote(copies[i]));
            if (ids[i] && probe::is_target_version(copies[i])) { ++targets; selectedId=ids[i]; selectedName=copies[i]; }
        }
        if (targets!=1) throw std::runtime_error("exactly one returned 4.1.1 provider required; no fallback");
    }
    void initialize(ID3D12Device *dev) {
        enumerate(dev);
        api.reportModules();
        desc.header.type=FFX_API_CREATE_CONTEXT_DESC_TYPE_UPSCALE;
        desc.flags=FFX_UPSCALE_ENABLE_DEBUG_CHECKING; desc.maxRenderSize={rw,rh}; desc.maxUpscaleSize={ow,oh}; desc.fpMessage=message;
        backend.header.type=FFX_API_CREATE_CONTEXT_DESC_TYPE_BACKEND_DX12; backend.device=dev;
        overrideDesc.header.type=FFX_API_DESC_TYPE_OVERRIDE_VERSION; overrideDesc.versionId=selectedId;
        version.header.type=FFX_API_CREATE_CONTEXT_DESC_TYPE_UPSCALE_VERSION; version.version=FFX_UPSCALER_VERSION;
        desc.header.pNext=&backend.header; backend.header.pNext=&overrideDesc.header; overrideDesc.header.pNext=&version.header;
        stage("provider_memory_budget");
        FfxApiEffectMemoryUsage memory{};
        ffxQueryDescUpscaleGetGPUMemoryUsageV2 usage{}; usage.header.type=FFX_API_QUERY_DESC_TYPE_UPSCALE_GPU_MEMORY_USAGE_V2;
        ffxOverrideVersion memoryOverride{};
        memoryOverride.header.type=FFX_API_DESC_TYPE_OVERRIDE_VERSION;
        memoryOverride.versionId=selectedId;
        usage.header.pNext=&memoryOverride.header; usage.device=dev; usage.flags=desc.flags;
        usage.maxRenderSize=desc.maxRenderSize; usage.maxUpscaleSize=desc.maxUpscaleSize; usage.gpuMemoryUsageUpscaler=&memory;
        api.rc("ffxQuery selected provider memory V2",api.query(nullptr,&usage.header));
        event("\"event\":\"sdk_memory_estimate\",\"total_bytes\":"+std::to_string(memory.totalUsageInBytes)+
              ",\"aliasable_bytes\":"+std::to_string(memory.aliasableUsageInBytes)+",\"budget_bytes\":"+std::to_string(budget));
        if (!memory.totalUsageInBytes || memory.totalUsageInBytes>budget-(UINT64_C(4)<<20))
            throw std::runtime_error("SDK memory estimate missing or exceeds budget");
        stage("context_creation");
        event("\"event\":\"context_request\",\"provider_id\":"+probe::json_quote(hex64(selectedId))+
              ",\"api_version\":"+std::to_string(version.version)+",\"render_width\":64,\"render_height\":64,\"output_width\":96,\"output_height\":96");
        api.rc("ffxCreateContext explicit 4.1.1",api.create(&value,&desc.header,nullptr));
        if (!value) throw std::runtime_error("successful create returned null context");
        stage("context_provider_query");
        ffxQueryGetProviderVersion q{}; q.header.type=FFX_API_QUERY_DESC_TYPE_GET_PROVIDER_VERSION;
        api.rc("ffxQuery context provider",api.query(&value,&q.header));
        const std::string name=q.versionName?q.versionName:"";
        const bool match=q.versionId==selectedId && q.versionName && probe::is_target_version(name);
        event("\"event\":\"context_provider\",\"id\":"+probe::json_quote(hex64(q.versionId))+
              ",\"name_bytes\":"+probe::json_quote(name)+",\"selected_id_matches\":"+(match?"true":"false"));
        if (!match) throw std::runtime_error("context did not retain selected 4.1.1 provider");
    }
    void close() { if (value) api.rc("ffxDestroyContext",api.destroy(&value,nullptr)); }
};
static void barrier(ID3D12GraphicsCommandList *list,ID3D12Resource *res,D3D12_RESOURCE_STATES before,D3D12_RESOURCE_STATES after) {
    if (before==after) return;
    D3D12_RESOURCE_BARRIER b{}; b.Type=D3D12_RESOURCE_BARRIER_TYPE_TRANSITION;
    b.Transition.pResource=res; b.Transition.Subresource=D3D12_RESOURCE_BARRIER_ALL_SUBRESOURCES;
    b.Transition.StateBefore=before; b.Transition.StateAfter=after; list->ResourceBarrier(1,&b);
}
static D3D12_HEAP_PROPERTIES heap(D3D12_HEAP_TYPE type) {
    D3D12_HEAP_PROPERTIES p{}; p.Type=type; p.CreationNodeMask=1; p.VisibleNodeMask=1; return p;
}
static void buffer(ID3D12Device *dev,UINT64 size,D3D12_HEAP_TYPE type,Com<ID3D12Resource> &out) {
    D3D12_RESOURCE_DESC d{}; d.Dimension=D3D12_RESOURCE_DIMENSION_BUFFER; d.Width=size; d.Height=1;
    d.DepthOrArraySize=1; d.MipLevels=1; d.SampleDesc.Count=1; d.Layout=D3D12_TEXTURE_LAYOUT_ROW_MAJOR;
    const auto p=heap(type);
    hr("CreateCommittedResource buffer",dev->CreateCommittedResource(&p,D3D12_HEAP_FLAG_NONE,&d,
       type==D3D12_HEAP_TYPE_UPLOAD?D3D12_RESOURCE_STATE_GENERIC_READ:D3D12_RESOURCE_STATE_COPY_DEST,nullptr,IID_PPV_ARGS(out.put())));
}
struct Texture {
    Com<ID3D12Resource> image,upload;
    D3D12_PLACED_SUBRESOURCE_FOOTPRINT footprint{};
    UINT64 total=0; UINT rowBytes=0;
    D3D12_RESOURCE_STATES state=D3D12_RESOURCE_STATE_COPY_DEST;
    void create(ID3D12Device *dev,UINT w,UINT h,DXGI_FORMAT format,UINT bytesPerPixel,bool output=false) {
        rowBytes=w*bytesPerPixel;
        D3D12_RESOURCE_DESC d{}; d.Dimension=D3D12_RESOURCE_DIMENSION_TEXTURE2D; d.Width=w; d.Height=h;
        d.DepthOrArraySize=1; d.MipLevels=1; d.Format=format; d.SampleDesc.Count=1;
        if (output) d.Flags=D3D12_RESOURCE_FLAG_ALLOW_UNORDERED_ACCESS;
        const auto p=heap(D3D12_HEAP_TYPE_DEFAULT);
        hr("CreateCommittedResource texture",dev->CreateCommittedResource(&p,D3D12_HEAP_FLAG_NONE,&d,
            D3D12_RESOURCE_STATE_COPY_DEST,nullptr,IID_PPV_ARGS(image.put())));
        dev->GetCopyableFootprints(&d,0,1,0,&footprint,nullptr,nullptr,&total);
        if (!total || total>(UINT64_C(1)<<20)) throw std::runtime_error("unexpected texture footprint");
        buffer(dev,total,D3D12_HEAP_TYPE_UPLOAD,upload);
    }
    void fill(const std::vector<unsigned char> &packed) {
        if (packed.size()!=static_cast<size_t>(rowBytes)*footprint.Footprint.Height) throw std::runtime_error("upload size mismatch");
        void *mapping=nullptr; D3D12_RANGE none{0,0}; hr("Map upload",upload->Map(0,&none,&mapping));
        for (UINT y=0;y<footprint.Footprint.Height;++y)
            std::memcpy(static_cast<unsigned char *>(mapping)+footprint.Offset+y*footprint.Footprint.RowPitch,
                        packed.data()+static_cast<size_t>(y)*rowBytes,rowBytes);
        const D3D12_RANGE written{0,static_cast<SIZE_T>(total)}; upload->Unmap(0,&written);
    }
    void copy(ID3D12GraphicsCommandList *list,D3D12_RESOURCE_STATES desired) {
        barrier(list,image.get(),state,D3D12_RESOURCE_STATE_COPY_DEST);
        D3D12_TEXTURE_COPY_LOCATION dst{}; dst.pResource=image.get(); dst.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        D3D12_TEXTURE_COPY_LOCATION src{}; src.pResource=upload.get(); src.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT; src.PlacedFootprint=footprint;
        list->CopyTextureRegion(&dst,0,0,0,&src,nullptr);
        barrier(list,image.get(),D3D12_RESOURCE_STATE_COPY_DEST,desired); state=desired;
    }
};
static std::vector<unsigned char> bytes(const std::vector<float> &floats) {
    std::vector<unsigned char> b(floats.size()*sizeof(float)); std::memcpy(b.data(),floats.data(),b.size()); return b;
}
struct Commands {
    Com<ID3D12CommandQueue> queue; Com<ID3D12CommandAllocator> allocator;
    Com<ID3D12GraphicsCommandList> list; Com<ID3D12Fence> fence; Handle done; UINT64 sequence=0;
    bool pending=false;
    void initialize(ID3D12Device *dev) {
        D3D12_COMMAND_QUEUE_DESC q{}; q.Type=D3D12_COMMAND_LIST_TYPE_DIRECT;
        hr("CreateCommandQueue",dev->CreateCommandQueue(&q,IID_PPV_ARGS(queue.put())));
        hr("CreateCommandAllocator",dev->CreateCommandAllocator(q.Type,IID_PPV_ARGS(allocator.put())));
        hr("CreateCommandList",dev->CreateCommandList(0,q.Type,allocator.get(),nullptr,IID_PPV_ARGS(list.put())));
        hr("initial command list Close",list->Close());
        hr("CreateFence",dev->CreateFence(0,D3D12_FENCE_FLAG_NONE,IID_PPV_ARGS(fence.put())));
        done.value=CreateEventW(nullptr,FALSE,FALSE,nullptr);
        if (!done.value) throw std::runtime_error("CreateEventW failed");
    }
    void begin() {
        if (pending) throw std::runtime_error("allocator still in use");
        hr("command allocator Reset",allocator->Reset()); hr("command list Reset",list->Reset(allocator.get(),nullptr));
    }
    void submit() {
        hr("command list Close",list->Close());
        ID3D12CommandList *lists[]={list.get()}; queue->ExecuteCommandLists(1,lists); pending=true;
        const auto signalCode=hr("command queue Signal",queue->Signal(fence.get(),++sequence),false);
        const auto eventCode=SUCCEEDED(signalCode)?
            hr("fence SetEventOnCompletion",fence->SetEventOnCompletion(sequence,done.value),false):E_FAIL;
        const DWORD result=SUCCEEDED(signalCode) && SUCCEEDED(eventCode)?
            WaitForSingleObject(done.value,60000):WAIT_FAILED;
        event("\"event\":\"fence_wait\",\"result\":"+std::to_string(result)+",\"sequence\":"+std::to_string(sequence));
        if (result!=WAIT_OBJECT_0) {
            // Do not release resources that queued GPU work may still reference.
            event("\"event\":\"error\",\"stage\":\"fence_wait\",\"message\":\"GPU fence timeout/error; terminating without releasing in-flight objects\",\"ml_dispatch_verified\":false");
            std::cout.flush(); TerminateProcess(GetCurrentProcess(),3);
            throw std::runtime_error("TerminateProcess failed after fence timeout");
        }
        pending=false;
    }
};
static void readOutput(Texture &output,ID3D12Resource *readback,unsigned frame,float jx,float jy,bool reset) {
    stage("output_readback"); void *mapped=nullptr; const D3D12_RANGE range{0,static_cast<SIZE_T>(output.total)};
    hr("Map readback",readback->Map(0,&range,&mapped));
    uint64_t hash=UINT64_C(14695981039346656037),changed=0,finite=0;
    float minimum=std::numeric_limits<float>::infinity(),maximum=-minimum;
    for (UINT y=0;y<oh;++y) {
        const auto *row=static_cast<const unsigned char *>(mapped)+output.footprint.Offset+y*output.footprint.Footprint.RowPitch;
        hash=probe::fnv1a(row,output.rowBytes,hash);
        for (UINT x=0;x<ow*4;++x) {
            float val; std::memcpy(&val,row+x*sizeof(float),sizeof(val));
            if (val!=-123.0f) ++changed;
            if (std::isfinite(val)) { ++finite; minimum=std::min(minimum,val); maximum=std::max(maximum,val); }
        }
    }
    const D3D12_RANGE unwritten{0,0}; readback->Unmap(0,&unwritten);
    std::ostringstream s; s<<std::setprecision(9)<<
        "\"event\":\"dispatch_readback\",\"frame\":"<<frame<<",\"jitter_x\":"<<jx<<",\"jitter_y\":"<<jy<<
        ",\"reset\":"<<(reset?"true":"false")<<",\"hash_fnv1a64\":"<<probe::json_quote(hex64(hash))<<
        ",\"changed_components\":"<<changed<<",\"finite_components\":"<<finite<<
        ",\"min_finite\":"<<(std::isfinite(minimum)?std::to_string(minimum):"null")<<
        ",\"max_finite\":"<<(std::isfinite(maximum)?std::to_string(maximum):"null")<<",\"ml_dispatch_verified\":false";
    event(s.str());
    if (changed!=ow*oh*4 || finite!=ow*oh*4) throw std::runtime_error("output incomplete, sentinel unchanged or non-finite");
}
static void requirements(Context &ctx) {
    stage("resource_requirements");
    ffxQueryDescUpscaleGetResourceRequirements q{}; q.header.type=FFX_API_QUERY_DESC_TYPE_UPSCALE_GET_RESOURCE_REQUIREMENTS;
    ctx.api.rc("ffxQuery resource requirements",ctx.api.query(&ctx.value,&q.header));
    event("\"event\":\"resource_requirements\",\"required\":"+std::to_string(q.required_resources)+",\"optional\":"+std::to_string(q.optional_resources));
    const uint64_t supplied=FFX_API_QUERY_RESOURCE_INPUT_COLOR|FFX_API_QUERY_RESOURCE_INPUT_DEPTH|
        FFX_API_QUERY_RESOURCE_INPUT_MV|FFX_API_QUERY_RESOURCE_INPUT_EXPOSURE|
        FFX_API_QUERY_RESOURCE_INPUT_REACTIVEMASK|FFX_API_QUERY_RESOURCE_INPUT_TRANSPARENCYCOMPOSITION;
    if (q.required_resources&~supplied) throw std::runtime_error("provider requires unhandled input");
}
struct Inputs {
    Texture color,depth,motion,exposure,reactive,composition,output;
    Com<ID3D12Resource> readback;
    void initialize(ID3D12Device *dev) {
        color.create(dev,rw,rh,DXGI_FORMAT_R32G32B32A32_FLOAT,16);
        depth.create(dev,rw,rh,DXGI_FORMAT_R32_FLOAT,4);
        motion.create(dev,rw,rh,DXGI_FORMAT_R32G32_FLOAT,8);
        exposure.create(dev,1,1,DXGI_FORMAT_R32_FLOAT,4);
        reactive.create(dev,rw,rh,DXGI_FORMAT_R8_UNORM,1);
        composition.create(dev,rw,rh,DXGI_FORMAT_R8_UNORM,1);
        output.create(dev,ow,oh,DXGI_FORMAT_R32G32B32A32_FLOAT,16,true);
        buffer(dev,output.total,D3D12_HEAP_TYPE_READBACK,readback);
        const uint64_t appBytes=2*(color.total+depth.total+motion.total+exposure.total+reactive.total+composition.total)+3*output.total;
        event("\"event\":\"app_resource_bytes\",\"bytes_with_upload_readback\":"+std::to_string(appBytes));
        if (appBytes>(UINT64_C(4)<<20)) throw std::runtime_error("app buffers exceed budget allowance");
        // Finite conventional perspective depth for a plane two metres away.
        const float n=0.1f,f=100.0f,z=2.0f;
        const float planeDepth=f/(f-n)-(f*n)/((f-n)*z);
        depth.fill(bytes(std::vector<float>(rw*rh,planeDepth)));
        motion.fill(bytes(std::vector<float>(rw*rh*2,0.0f)));
        exposure.fill(bytes(std::vector<float>{1.0f}));
        reactive.fill(std::vector<unsigned char>(rw*rh,0)); composition.fill(std::vector<unsigned char>(rw*rh,0));
        output.fill(bytes(std::vector<float>(ow*oh*4,-123.0f)));
    }
    void fillColor(float jx,float jy) {
        std::vector<float> pixels(rw*rh*4);
        // Sample a static analytic plane at the jittered pixel centres; motion
        // vectors describe unjittered static motion and are therefore exactly zero.
        for (UINT y=0;y<rh;++y) for (UINT x=0;x<rw;++x) {
            const float u=(x+0.5f+jx)/rw,v=(y+0.5f+jy)/rh;
            const size_t i=(static_cast<size_t>(y)*rw+x)*4;
            pixels[i]=0.1f+0.7f*u; pixels[i+1]=0.1f+0.7f*v;
            pixels[i+2]=0.3f+0.2f*std::sin(30.0f*u)*std::sin(30.0f*v); pixels[i+3]=1.0f;
        }
        color.fill(bytes(pixels));
    }
    void upload(ID3D12GraphicsCommandList *list,unsigned frame) {
        color.copy(list,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
        if (frame==0) {
            depth.copy(list,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
            motion.copy(list,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
            exposure.copy(list,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
            reactive.copy(list,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
            composition.copy(list,D3D12_RESOURCE_STATE_NON_PIXEL_SHADER_RESOURCE);
        }
        // Reinitialize the output sentinel per frame, without altering SDK history.
        output.copy(list,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
    }
    ffxDispatchDescUpscale descriptor(ID3D12GraphicsCommandList *list,unsigned frame,float jx,float jy) {
        ffxDispatchDescUpscale d{}; d.header.type=FFX_API_DISPATCH_DESC_TYPE_UPSCALE; d.commandList=list;
        d.color=ffxApiGetResourceDX12(color.image.get()); d.depth=ffxApiGetResourceDX12(depth.image.get());
        d.motionVectors=ffxApiGetResourceDX12(motion.image.get()); d.exposure=ffxApiGetResourceDX12(exposure.image.get());
        d.reactive=ffxApiGetResourceDX12(reactive.image.get()); d.transparencyAndComposition=ffxApiGetResourceDX12(composition.image.get());
        d.output=ffxApiGetResourceDX12(output.image.get(),FFX_API_RESOURCE_STATE_UNORDERED_ACCESS);
        d.jitterOffset={jx,jy}; d.motionVectorScale={static_cast<float>(rw),static_cast<float>(rh)};
        d.renderSize={rw,rh}; d.upscaleSize={ow,oh}; d.frameTimeDelta=16.6667f; d.preExposure=1.0f; d.reset=frame==0;
        d.cameraNear=0.1f; d.cameraFar=100.0f; d.cameraFovAngleVertical=1.04719755f; d.viewSpaceToMetersFactor=1.0f;
        return d;
    }
    void copyReadback(ID3D12GraphicsCommandList *list) {
        // SDK imported external resources return to their supplied initial states.
        D3D12_RESOURCE_BARRIER uav{}; uav.Type=D3D12_RESOURCE_BARRIER_TYPE_UAV; uav.UAV.pResource=output.image.get();
        list->ResourceBarrier(1,&uav);
        barrier(list,output.image.get(),D3D12_RESOURCE_STATE_UNORDERED_ACCESS,D3D12_RESOURCE_STATE_COPY_SOURCE);
        D3D12_TEXTURE_COPY_LOCATION dst{}; dst.pResource=readback.get(); dst.Type=D3D12_TEXTURE_COPY_TYPE_PLACED_FOOTPRINT; dst.PlacedFootprint=output.footprint;
        D3D12_TEXTURE_COPY_LOCATION src{}; src.pResource=output.image.get(); src.Type=D3D12_TEXTURE_COPY_TYPE_SUBRESOURCE_INDEX;
        list->CopyTextureRegion(&dst,0,0,0,&src,nullptr);
        barrier(list,output.image.get(),D3D12_RESOURCE_STATE_COPY_SOURCE,D3D12_RESOURCE_STATE_UNORDERED_ACCESS);
    }
};
static void dispatch(Context &ctx,ID3D12Device *dev,unsigned frames) {
    requirements(ctx); stage("app_resource_creation");
    Commands command; command.initialize(dev); Inputs input; input.initialize(dev);
    int32_t phases=0; ffxQueryDescUpscaleGetJitterPhaseCount phase{};
    phase.header.type=FFX_API_QUERY_DESC_TYPE_UPSCALE_GETJITTERPHASECOUNT;
    phase.renderWidth=rw; phase.displayWidth=ow; phase.pOutPhaseCount=&phases;
    ctx.api.rc("ffxQuery jitter phase count",ctx.api.query(&ctx.value,&phase.header));
    if (phases<1 || phases>1024) throw std::runtime_error("invalid jitter phase count");
    for (unsigned frame=0;frame<frames;++frame) {
        stage("jitter_query"); float jx=0,jy=0; ffxQueryDescUpscaleGetJitterOffset q{};
        q.header.type=FFX_API_QUERY_DESC_TYPE_UPSCALE_GETJITTEROFFSET;
        q.index=static_cast<int32_t>(frame); q.phaseCount=phases; q.pOutX=&jx; q.pOutY=&jy;
        ctx.api.rc("ffxQuery jitter offset",ctx.api.query(&ctx.value,&q.header));
        if (!std::isfinite(jx) || !std::isfinite(jy) || std::abs(jx)>1 || std::abs(jy)>1)
            throw std::runtime_error("invalid SDK jitter offset");
        input.fillColor(jx,jy); stage("command_recording"); command.begin(); input.upload(command.list.get(),frame);
        const auto d=input.descriptor(command.list.get(),frame,jx,jy);
        stage("ffx_dispatch"); ctx.api.rc("ffxDispatch synthetic upscale",ctx.api.dispatch(&ctx.value,&d.header));
        input.copyReadback(command.list.get());
        stage("queue_submit_and_wait"); command.submit(); hr("GetDeviceRemovedReason",dev->GetDeviceRemovedReason());
        readOutput(input.output,input.readback.get(),frame,jx,jy,d.reset);
    }
}
} // namespace
int wmain(int argc,wchar_t **argv) {
    try {
        const Options o=options(argc,argv);
        event("\"event\":\"probe_start\",\"mode\":"+probe::json_quote(o.dispatch?"dispatch":"query-only")+
              ",\"input_kind\":\"synthetic_static_plane_minimal_diagnostic\",\"sdk_header_api_version\":"+std::to_string(FFX_UPSCALER_VERSION)+
              ",\"ml_dispatch_verified\":false");
        stage("load_signed_sdk"); Api api; api.load(o);
        ffxConfigureDescGlobalDebug debug{}; debug.header.type=FFX_API_CONFIGURE_DESC_TYPE_GLOBALDEBUG;
        debug.effectId=FFX_API_EFFECT_ID_UPSCALE; debug.fpMessage=message; debug.debugLevel=FFX_API_CONFIGURE_GLOBALDEBUG_LEVEL_VERBOSE;
        api.rc("ffxConfigure global upscale debug",api.configure(nullptr,&debug.header),false);
        stage("amd_device_creation"); Com<ID3D12Device> dev; device(o,dev);
        Context ctx(api); ctx.initialize(dev.get());
        if (o.dispatch) dispatch(ctx,dev.get(),o.frames);
        stage("context_destruction"); ctx.close(); stage("complete");
        event("\"event\":\"result\",\"context_provider_verified\":true,\"dispatch_readback_completed\":"+
              std::string(o.dispatch?"true":"false")+",\"ml_dispatch_verified\":false,\"ml_evidence_status\":\"unresolved_requires_shader_or_trace_discriminator\"");
        return 0;
    } catch (const std::exception &e) {
        event("\"event\":\"error\",\"stage\":"+probe::json_quote(currentStage)+",\"message\":"+probe::json_quote(e.what())+
              ",\"ml_dispatch_verified\":false"); return 1;
    }
}
